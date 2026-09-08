"""Append-only host receipts. Audit recomputes guards; stored acceptance is never authority."""
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from protocol import digest, require, Rejected, check_inventory, check_response, check_closure, axes, verdict, escape_ids, blocks, inv, protocol_escapes, check_extra_round

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent


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
    check('executor-exit', lambda: require((directory / 'executor-exit.txt').read_text().strip() == '0',
                                           'executor-exit', 'executor failed; see executor.err'))
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
        if end:
            verify_hashes(d, end['outputs'])
        if end and end['executed']:
            checks = recompute(repo, d, start)
            # Historical checkout checks cannot be rerun after removing the worktree;
            # its exact commit was captured by the host at finish, and is bound in outputs.
            require((d / 'checkout-head.txt').read_text().strip() == start['head_sha'],
                    'checkout', f'round {n}: checkout did not match')
            historical = [c for c in end['guards'] if c['guard'] not in {'checkout', 'seal-location'}]
            require(checks == historical, 'ledger-guards', f'round {n}: recomputed guards differ')
            text = (d / 'ARTIFACT.md').read_text()
            stats = statistics(text, start['phase'])
            require(all(end[k] == v for k, v in stats.items()), 'ledger-counts', f'round {n}: counts differ from artifact')
            expected_inventory = digest((d / 'ARTIFACT.md').read_bytes()) if start['phase'] == 1 else start['inventory_sha256']
            require(end['inventory_sha256'] == expected_inventory, 'ledger-digest', f'round {n}: inventory digest differs')
            require(end['accepted'] == all(c['ok'] for c in end['guards']), 'ledger-guards', f'round {n}: forged acceptance')
            if start['phase'] == 1 and end['accepted']:
                originals.append((n, d, start, text))
        if start['round'] >= 3 and end and end['executed']:
            require(originals, 'round-budget', 'no sealed round-1 inventory')
            first = originals[0]
            prior_review = max((k for k, e in ends.items() if k < n and e.get('executed')), default=n - 1)
            prior_file = root / f'round-{prior_review:04}' / 'ARTIFACT.md'
            prior_escape = prior_file.parent / 'ESCAPES.md'
            check_extra_round((d / 'ESCAPES.md').read_text(), first[3],
                              prior_file.read_text() if prior_file.exists() else '', starts[prior_review]['phase'],
                              ends.get(n - 1, {}).get('accepted', False),
                              start['head_sha'] != starts[prior_review]['head_sha'],
                              prior_escape.read_text() if prior_escape.exists() else '')
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



def report(root, repo):
    starts, ends, originals = audit(root, repo)
    print('round phase head inventory items FAIL guards verdict')
    escaped = set()
    escape_rates = {digest((o[1] / 'ARTIFACT.md').read_bytes()): (set(), len(blocks(o[3], 'Inventory'))) for o in originals}
    for n, s in starts.items():
        e = ends.get(n, {})
        invsha = s.get('inventory_sha256') or e.get('inventory_sha256') or '-'
        print(n, s['phase'], s['head_sha'], invsha, e.get('item_count', '-'), e.get('fail_count', '-'),
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
    print('The rate includes named causes of extra rounds; ROUND1-ESCAPE is reported separately in the evidence.')
    return starts, ends
