"""Append-only host receipts. Audit recomputes guards; stored acceptance is never authority."""
import json
import re
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from protocol import digest, protocol_sha256, require, Rejected, check_inventory, check_response, check_closure, axes, verdict, escape_ids, blocks, inv, protocol_escapes, check_extra_round

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
# The version of the protocol a receipt was produced under. A round records this at start;
# audit compares it before deciding whether recomputed guard results are comparable at all.


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def append(root, event):
    path = root / 'ledger.jsonl'
    previous = path.read_bytes().splitlines()[-1] if path.exists() and path.stat().st_size else b''
    event = dict(event, previous_sha256=digest(previous), at=datetime.now(timezone.utc).isoformat())
    raw = encode(event) + b'\n'
    with path.open('ab') as f:
        f.write(raw)
        f.flush()
        import os
        os.fsync(f.fileno())
    return event


def read(root):
    path = root / 'ledger.jsonl'
    if not path.exists():
        return []
    events, previous = [], b''
    for raw in path.read_bytes().splitlines():
        e = json.loads(raw)
        require(e['previous_sha256'] == digest(previous), 'ledger-integrity', 'broken receipt chain')
        events.append(e)
        previous = raw
    return events


def hashes(directory, names):
    return {name: digest((directory / name).read_bytes()) for name in names}


def verify_hashes(directory, expected):
    for name, sha in expected.items():
        require(Path(name).name == name, 'ledger-integrity', 'invalid artifact path')
        p = directory / name
        require(p.is_file() and not p.is_symlink() and digest(p.read_bytes()) == sha,
                'ledger-integrity', f'{directory.name}/{name}: digest mismatch')


def shell_guard(name, *args):
    p = subprocess.run(['bash', '-c', 'source "$1"; shift; "$@"', 'guards',
                        str(HERE / 'guards.sh'), name, *map(str, args)], capture_output=True, text=True)
    require(p.returncode == 0, name, p.stderr.strip().replace('\n', '; '))


def recompute(repo, directory, start, checkout=None):
    """Used both immediately after execution and on audit, with host-owned code."""
    checks = []
    def check(name, fn):
        try:
            fn()
            checks.append({'guard': name, 'ok': True})
        except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
            checks.append({'guard': name, 'ok': False, 'reason': str(e).replace('\n', '; ')})
    def inputs():
        mandatory = {'SEAL.txt', 'inventory.txt', 'DIFF.patch', 'CHANGED.txt', 'prompt.txt'}
        if start['phase'] == 2:
            mandatory |= {'ROUND1_INVENTORY.md', 'IMPLEMENTER_RESPONSE.md', 'REMEDIATION.patch',
                          'REMEDIATION_CHANGED.txt', 'REMEDIATION_HUNKS.md'}
            require(digest((directory / 'ROUND1_INVENTORY.md').read_bytes()) == start['inventory_sha256'],
                    'inventory-integrity', 'round-1 copy differs from trusted digest')
        require(mandatory <= start['inputs'].keys(), 'input-digests', 'required input digest missing')
        verify_hashes(directory, start['inputs'])
    check('input-digests', inputs)
    # Refusing on a non-zero exit stays the default: a round whose executor died is not evidence,
    # and nothing here can tell a death from a drop. But the two are not the same event, and the
    # message should not read as though they were -- reported: a run reconnected, kept producing
    # events, and closed a well-formed inventory, and the refusal said only "executor failed".
    # Say the code, and say whether an artifact was written, so the reader can tell which happened.
    def executor_exit():
        code = (directory / 'executor-exit.txt').read_text().strip()
        artifact = directory / 'ARTIFACT.md'
        wrote = artifact.exists() and artifact.stat().st_size > 0
        require(code == '0', 'executor-exit',
                'executor exited %s; see executor.err. An artifact %s written -- a transport that '
                'dropped and recovered leaves one, an executor that died does not, and this check '
                'refuses either way.'
                % (code, 'WAS' if wrote else 'was not'))
    check('executor-exit', executor_exit)
    for name in ('guard_turn_completed', 'guard_cmds_nonzero', 'guard_seal_unseen'):
        args = [directory / 'events.jsonl'] + ([directory] if name == 'guard_seal_unseen' else [])
        check(name, lambda name=name, args=args: shell_guard(name, *args))
    marker = '# Round 1 review inventory' if start['phase'] == 1 else '# Round 2 closure review'
    def extracted():
        p = subprocess.run([sys.executable, str(HERE / 'extract.py'), str(directory / 'events.jsonl'), marker], capture_output=True)
        require(p.returncode == 0 and p.stdout == (directory / 'ARTIFACT.md').read_bytes(),
                'last-message', 'artifact is not the final executor message')
    check('last-message', extracted)
    text = (directory / 'ARTIFACT.md').read_text() if (directory / 'ARTIFACT.md').exists() else ''
    check('guard_no_placeholder', lambda: shell_guard('guard_no_placeholder', directory / 'ARTIFACT.md'))
    def target():
        p = subprocess.run([str(SCRIPTS / 'target-seal.sh'), 'verify', str(repo), str(directory), start['head_sha']],
                           capture_output=True, text=True)
        require(p.returncode == 0, 'target', p.stderr.strip())
    check('target', target)
    if checkout:
        check('checkout', lambda: shell_guard('guard_seal_head_crosscheck', directory, checkout, start['head_sha']))
        check('seal-location', lambda: shell_guard('guard_no_seal_in_tree', checkout))
    if start['phase'] == 1:
        check('inventory', lambda: check_inventory(text, repo, start['base_sha'], start['head_sha'], start['expected_ids']))
    else:
        inventory = (directory / 'ROUND1_INVENTORY.md').read_text()
        sha = start['inventory_sha256']
        check('hunk-accounting', lambda: check_response((directory / 'IMPLEMENTER_RESPONSE.md').read_text(), inventory,
                                                       repo, start['round1_head_sha'], start['head_sha'], sha))
        check('closure', lambda: check_closure(text, inventory, start['head_sha'], sha))
    return checks


def audit(root, repo):
    events = read(root)
    starts, ends = {}, {}
    for e in events:
        n = e['round']
        if e['event'] == 'started':
            require(n == len(starts) + 1, 'ledger-rounds', 'round numbers were skipped or reset')
            starts[n] = e
        else:
            require(e.get('executed') or not e.get('accepted'), 'ledger-guards',
                    'an unexecuted attempt cannot claim acceptance')
            require(e['event'] == 'finished' and n in starts and n not in ends,
                    'ledger-rounds', 'orphan or duplicate round result')
            ends[n] = e
    originals = []
    for n, start in starts.items():
        d = root / f'round-{n:04}'
        verify_hashes(d, start['inputs'])
        end = ends.get(n)
        if start['phase'] == 2 and start.get('inventory_sha256'):
            require(originals, 'ledger-handoff', f'round {n}: no earlier sealed inventory')
            original = originals[-1]
            require(start['inventory_sha256'] == digest((original[1] / 'ARTIFACT.md').read_bytes()) and
                    start['round1_head_sha'] == original[2]['head_sha'] and
                    start['base_sha'] == original[2]['base_sha'], 'ledger-handoff', f'round {n}: handoff substituted')
        pending_original = None
        if end:
            verify_hashes(d, end['outputs'])
        if end and end['executed']:
            checks = recompute(repo, d, start)
            # Historical checkout checks cannot be rerun after removing the worktree;
            # its exact commit was captured by the host at finish, and is bound in outputs.
            require((d / 'checkout-head.txt').read_text().strip() == start['head_sha'],
                    'checkout', f'round {n}: checkout did not match')
            historical = [c for c in end['guards'] if c['guard'] not in {'checkout', 'seal-location'}]
            # Recomputation catches a receipt that claims guard results the guards do not give.
            # It can only say that about the guards that ran. When the skill has moved since --
            # and it moves whenever one of these checks is corrected -- a difference is the
            # correction, not a forgery, and treating it as one condemns every earlier round in
            # the ledger. Measured: eight guard fixes in one afternoon would have bricked a real
            # PR's whole receipt chain, and the way out of that is to delete the ledger, which
            # destroys the round history it exists to keep.
            #
            # The artifact bytes stay bound either way: outputs are hashed at finish and verified
            # above, so substituting a round's contents is still caught. What is dropped here is
            # only the claim that today's guards agree with yesterday's.
            # Two of this function's checks RECOMPUTE something and compare it to what the
            # receipt recorded: the guard results, and the counts derived from the artifact. Both
            # only speak for the code that produced the receipt. Correcting a parser changes what
            # today's code derives from yesterday's bytes, so across a protocol version a
            # difference is the correction, not a forgery -- and treating it as one condemns every
            # earlier round, whose only remedy is deleting the ledger and with it the round history
            # it exists to keep. Scoping the guard check alone left this one open and the next
            # round hit it, which is why they now sit together under one flag: a third
            # recomputation belongs here, beside its siblings.
            #
            # Nothing that rests on BYTES moves: the receipt chain, the artifact digest, the
            # handoff binding and the receipt's own internal consistency are checked either way.
            same_protocol = start.get('skill_sha256') == protocol_sha256(SCRIPTS)
            if same_protocol:
                require(checks == historical, 'ledger-guards', f'round {n}: recomputed guards differ')
            else:
                require(end['accepted'] == all(c['ok'] for c in historical), 'ledger-guards',
                        f'round {n}: acceptance does not follow from its own recorded guards')
            text = (d / 'ARTIFACT.md').read_text()
            stats = statistics(text, start['phase'])
            require(not same_protocol or all(end[k] == v for k, v in stats.items()),
                    'ledger-counts', f'round {n}: counts differ from artifact')
            expected_inventory = digest((d / 'ARTIFACT.md').read_bytes()) if start['phase'] == 1 else start['inventory_sha256']
            require(end['inventory_sha256'] == expected_inventory, 'ledger-digest', f'round {n}: inventory digest differs')
            require(end['accepted'] == all(c['ok'] for c in end['guards']), 'ledger-guards', f'round {n}: forged acceptance')
            if start['phase'] == 1 and end['accepted']:
                # After the budget check below, never before it. A round is not its own prior
                # inventory: appending first makes an accepted round 3 demand a list of the items
                # that escaped from itself.
                pending_original = (n, d, start, text)
        # The sibling of the same rule in run-review.py, and it was left open when that one was
        # fixed -- the exact class-local repair this protocol exists to prevent, committed by its
        # own harness. Escapes presuppose an accepted inventory to escape FROM; where none of the
        # earlier attempts was accepted, round 1 has not happened yet and later attempts are it
        # happening again, not escapes from it.
        if originals and start['round'] >= 3 and end and end['executed']:
            first = originals[0]
            prior_review = max((k for k, e in ends.items() if k < n and e.get('executed')), default=n - 1)
            prior_file = root / f'round-{prior_review:04}' / 'ARTIFACT.md'
            prior_escape = prior_file.parent / 'ESCAPES.md'
            check_extra_round((d / 'ESCAPES.md').read_text(), first[3],
                              prior_file.read_text() if prior_file.exists() else '', starts[prior_review]['phase'],
                              ends.get(n - 1, {}).get('accepted', False),
                              start['head_sha'] != starts[prior_review]['head_sha'],
                              prior_escape.read_text() if prior_escape.exists() else '')
        if pending_original is not None:
            originals.append(pending_original)
            pending_original = None
    return starts, ends, originals


def statistics(text, phase):
    if phase == 1:
        items = inv.items(text)
        failures = sum(i['fields'].get('status') == 'FAIL' for i in items)
    else:
        import re
        items = re.findall(r'^### ([OGP]-\d+) — (CLOSED|OPEN|UNVERIFIABLE)\s*$', section_closure(text), re.M)
        regressions = set(re.findall(r'\bR-\d+\b', inv.section(text, '## Remediation regressions')))
        failures = sum(status != 'CLOSED' for _, status in items) + len(regressions)
        items += [(ident, 'OPEN') for ident in regressions]
    return {'item_count': len(items), 'fail_count': failures, 'verdict': verdict(text)}


def section_closure(text):
    return inv.section(text, '## Closure')



def guard_rejections(ends):
    """How often each guard has refused a round on this PR.

    A guard that refuses many rounds is either finding a real pattern or is itself the
    defect, and the difference is invisible while each refusal is met one at a time.
    Measured: eighteen harness faults in one day, every one found by a refusal and fixed by
    hand, and nothing recorded that the same three guards had done the refusing. Counting
    them does not decide which case it is -- it puts the question in front of whoever reads
    the report, at the moment the count is what makes it askable.
    """
    tally = {}
    for e in ends.values():
        for check in e.get('guards') or []:
            if not check.get('ok'):
                tally[check['guard']] = tally.get(check['guard'], 0) + 1
        reason = e.get('reason') or ''
        m = re.search(r'GUARD FAIL \[([a-z0-9-]+)\]', reason)
        if m:
            tally[m[1]] = tally.get(m[1], 0) + 1
    return dict(sorted(tally.items(), key=lambda kv: -kv[1]))


def report(root, repo):
    starts, ends, originals = audit(root, repo)
    print('round phase head inventory items FAIL guards verdict')
    print('  (a ? marks counts taken from an artifact the guards refused: read the artifact, not the number)')
    escaped = set()
    escape_rates = {digest((o[1] / 'ARTIFACT.md').read_bytes()): (set(), len(blocks(o[3], 'Inventory'))) for o in originals}
    for n, s in starts.items():
        e = ends.get(n, {})
        invsha = s.get('inventory_sha256') or e.get('inventory_sha256') or '-'
        # Counts from a REJECTED round are marked. They were derived from an artifact the guards
        # refused, by whatever parser ran at the time, and printing them bare invites the reading
        # that cost a reader an hour: a round showing `0` FAIL against an artifact carrying a
        # reproduced BLOCKER, read as "the first round found nothing".
        mark = '' if e.get('accepted') else '?'
        print(n, s['phase'], s['head_sha'], invsha,
              f"{e.get('item_count', '-')}{mark}", f"{e.get('fail_count', '-')}{mark}",
              'PASS' if e.get('accepted') else 'REJECTED' if e else 'INTERRUPTED', e.get('verdict') or '-')
        d = root / f'round-{n:04}'
        if e.get('executed') and e.get('accepted') and s['phase'] == 2 and originals:
            escape_rates[s['inventory_sha256']][0].update(ident for category, ident in protocol_escapes(
                (d / 'ARTIFACT.md').read_text(), (d / 'ROUND1_INVENTORY.md').read_text()) if category == 'ROUND1-ESCAPE')
        if (d / 'ESCAPES.md').exists() and originals:
            try:
                ids = escape_ids((d / 'ESCAPES.md').read_text(), originals[0][3])
            except Rejected:
                ids = []
            if e.get('executed'):
                escaped.update(ids)
            print('  ' + (d / 'ESCAPES.md').read_text().strip().replace('\n', '\n  '))
        if e.get('reason'):
            print('  ' + e['reason'])
        for c in e.get('guards', []):
            if not c['ok']:
                print('  ' + c['reason'])
    if originals:
        denominator = len(blocks(originals[0][3], 'Inventory'))
        for sha, (escaped_ids, item_count) in escape_rates.items():
            print(f'ROUND1-ESCAPE rate [{sha}]: {len(escaped_ids)}/{item_count} inventory items ({100 * len(escaped_ids) / item_count:.1f}%)')
        print(f'closure escape rate: {len(escaped)}/{denominator} original items ({100 * len(escaped) / denominator:.1f}%)')
    else:
        print('closure escape rate: unknown (no accepted round-1 inventory)')
    tally = guard_rejections(ends)
    if tally:
        print('guard refusals on this PR: ' + ', '.join(f'{g} x{c}' for g, c in tally.items()))
        repeated = [g for g, c in tally.items() if c >= 3]
        if repeated:
            print('  refused 3+ rounds: ' + ', '.join(repeated)
                  + ' -- either a real pattern in the change, or the guard is the defect. '
                    'Nothing here decides which; read the refused artifacts before the next round.')
    print('The rate includes named causes of extra rounds; ROUND1-ESCAPE is reported separately in the evidence.')
    return starts, ends
