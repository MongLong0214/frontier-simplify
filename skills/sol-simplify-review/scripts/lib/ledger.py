"""Host receipts preserve evidence, not merge permission. Legacy outcomes remain historical."""
import json
import re
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from protocol import digest, protocol_sha256, require, Rejected

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
MODE = 'prose-review-v2'


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def append(root, event):
    path = root / 'ledger.jsonl'
    previous = path.read_bytes().splitlines()[-1] if path.exists() and path.stat().st_size else b''
    event = dict(event, previous_sha256=digest(previous), at=datetime.now(timezone.utc).isoformat())
    with path.open('ab') as f:
        f.write(encode(event) + b'\n')
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
    """Only facts about execution, target and bytes. No prose is scored."""
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
            if start.get('mode') == MODE:
                mandatory.add('PREVIOUS_REVIEW.md')
            require(digest((directory / 'ROUND1_INVENTORY.md').read_bytes()) == start['inventory_sha256'],
                    'inventory-integrity', 'original review copy differs from trusted digest')
        require(mandatory <= start['inputs'].keys(), 'input-digests', 'required input digest missing')
        verify_hashes(directory, start['inputs'])
    check('input-digests', inputs)
    check('executor-exit', lambda: require((directory / 'executor-exit.txt').read_text().strip() == '0',
                                          'executor-exit', 'executor failed; see executor.err'))
    for name in ('guard_turn_completed', 'guard_cmds_nonzero', 'guard_seal_unseen'):
        args = [directory / 'events.jsonl'] + ([directory] if name == 'guard_seal_unseen' else [])
        check(name, lambda name=name, args=args: shell_guard(name, *args))
    def extracted():
        marker = '--final' if start.get('mode') == MODE else (
            '# Round 1 review inventory' if start['phase'] == 1 else '# Round 2 closure review')
        p = subprocess.run([sys.executable, str(HERE / 'extract.py'), str(directory / 'events.jsonl'), marker], capture_output=True)
        require(p.returncode == 0 and p.stdout == (directory / 'ARTIFACT.md').read_bytes(),
                'last-message', 'no nonempty final message, or artifact differs from executor output')
    check('last-message', extracted)
    def target():
        p = subprocess.run([str(SCRIPTS / 'target-seal.sh'), 'verify', str(repo), str(directory), start['head_sha']],
                           capture_output=True, text=True)
        require(p.returncode == 0, 'target', p.stderr.strip())
    check('target', target)
    check('checkout', lambda: require((directory / 'checkout-head.txt').read_text().strip() == start['head_sha'],
                                      'checkout', 'checkout did not match the reviewed head'))
    if checkout:
        check('seal-location', lambda: shell_guard('guard_no_seal_in_tree', checkout))
    return checks


def evidence_available(checks, end):
    # A removed checkout cannot be inspected again. Preserve its recorded physical failures.
    return bool(end.get('executed')) and all(c['ok'] for c in checks) and all(
        c['ok'] for c in end.get('guards', []) if c['guard'] in {'checkout', 'seal-location'})


def audit(root, repo):
    starts, ends, originals = {}, {}, []
    for e in read(root):
        n = e['round']
        if e['event'] == 'started':
            require(n == len(starts) + 1, 'ledger-rounds', 'round numbers were skipped or reset')
            starts[n] = e
        else:
            require(e['event'] == 'finished' and n in starts and n not in ends,
                    'ledger-rounds', 'orphan or duplicate round result')
            require(e.get('executed') or not (e.get('accepted') or e.get('recorded')),
                    'ledger-guards', 'an unexecuted attempt cannot claim a recorded review')
            ends[n] = e
    for n, start in starts.items():
        d = root / f'round-{n:04}'
        verify_hashes(d, start['inputs'])
        end = ends.get(n)
        if not end:
            continue
        verify_hashes(d, end['outputs'])
        if not end['executed'] or (end.get('reason') and not end.get('guards')):
            continue
        mandatory = {'ARTIFACT.md', 'events.jsonl', 'executor.err', 'executor-exit.txt', 'checkout-head.txt'}
        require(mandatory <= end['outputs'].keys(), 'ledger-integrity', 'required output digest missing')
        fresh = start.get('mode') == MODE
        result_key = 'recorded' if fresh else 'accepted'
        require(end[result_key] == all(c['ok'] for c in end['guards']),
                'ledger-guards', 'receipt result contradicts its recorded checks')
        require(not fresh or not end.get('accepted'), 'ledger-guards', 'a prose review cannot claim merge acceptance')
        checks = recompute(repo, d, start)
        if fresh and start.get('skill_sha256') == protocol_sha256(SCRIPTS):
            historical = [c for c in end['guards'] if c['guard'] != 'seal-location']
            require(checks == historical, 'ledger-guards', 'receipt checks differ from recomputation')
        usable = evidence_available(checks, end)
        if start['phase'] == 2 and start.get('inventory_sha256'):
            require(originals, 'ledger-handoff', 'no earlier original review')
            original = originals[-1]
            require(start['inventory_sha256'] == digest((original[1] / 'ARTIFACT.md').read_bytes()) and
                    start['round1_head_sha'] == original[2]['head_sha'] and
                    start['base_sha'] == original[2]['base_sha'], 'ledger-handoff', 'original review substituted')
            if fresh:
                prior = start['previous_round']
                require(prior < n and prior in ends and ends[prior].get('executed'),
                        'ledger-handoff', 'previous review is not an earlier executed attempt')
                require((d / 'PREVIOUS_REVIEW.md').read_bytes() ==
                        (root / f'round-{prior:04}' / 'ARTIFACT.md').read_bytes(),
                        'ledger-handoff', 'previous follow-up substituted')
        expected_sha = digest((d / 'ARTIFACT.md').read_bytes()) if start['phase'] == 1 else start.get('inventory_sha256')
        require(end['inventory_sha256'] == expected_sha, 'ledger-digest', 'review digest differs')
        if start['phase'] == 1 and usable:
            # A historical rejected review can supply evidence; its acceptance stays false.
            # Neither the old nor the new outcome becomes merge authorization.
            originals.append((n, d, start, (d / 'ARTIFACT.md').read_text()))
    return starts, ends, originals


def guard_rejections(ends):
    """Prefer recorded leaf reasons. Do not invent details absent from a legacy receipt."""
    tally = {}
    for e in ends.values():
        reasons = [(c['guard'], c.get('reason', '')) for c in e.get('guards', []) if not c['ok']]
        if e.get('reason'):
            reasons.append(('preflight', e['reason']))
        tags = set()
        for fallback, reason in reasons:
            found = re.findall(r'GUARD FAIL \[([a-z0-9_-]+)\]', reason)
            tags.add(found[-1] if found else fallback)
        for tag in tags:
            tally[tag] = tally.get(tag, 0) + 1
    return dict(sorted(tally.items(), key=lambda kv: (-kv[1], kv[0])))


def report(root, repo):
    starts, ends, originals = audit(root, repo)
    print('Review evidence only; no row or exit status authorizes a merge.')
    print('attempt phase head outcome artifact')
    for n, s in starts.items():
        e = ends.get(n, {})
        if s.get('mode') == MODE:
            outcome = 'RECORDED' if e.get('recorded') else 'FAILED' if e else 'INTERRUPTED'
        else:
            outcome = 'LEGACY_ACCEPTED' if e.get('accepted') else 'LEGACY_REJECTED' if e else 'INTERRUPTED'
        print(n, s['phase'], s['head_sha'], outcome, root / f'round-{n:04}' / 'ARTIFACT.md')
        if 'item_count' in e:
            print(f"  legacy parser counts (not distinct confirmed defects): {e['item_count']} items, {e.get('fail_count', '?')} FAIL")
        if e.get('reason'):
            print('  ' + e['reason'])
        for c in e.get('guards', []):
            if not c['ok']:
                print('  ' + c['reason'])
    tally = guard_rejections(ends)
    if tally:
        print('recorded refusal reasons: ' + ', '.join(f'{g} x{c}' for g, c in tally.items()))
        if 'inventory' in tally:
            print('  Legacy inventory detail was not recorded; inspect its artifact. No reason is inferred.')
    print(f'{len(starts)} attempts; {sum(bool(e.get("executed")) for e in ends.values())} executed. '
          'Safe merge completion is not measured by these receipts.')
    return starts, ends
