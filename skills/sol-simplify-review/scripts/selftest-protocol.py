#!/usr/bin/env python3
"""Offline behavior tests, including complete host runs and deliberate guard failures."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SCRIPTS = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SCRIPTS / 'lib'))
import protocol
from protocol import (Rejected, check_inventory, check_response, check_closure, escape_ids,
                      digest, hunks, hunk_markdown, blocks, check_extra_round)
import ledger
import importlib.util
from portability import check as portability

passed = failed = 0


def check(name, good, fn):
    global passed, failed
    try:
        result = fn()
        actual = result is not False
    except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        actual = False
        result = str(e)
    expected_tags = {
        'hunks-missing-one': 'hunk-accounting', 'hunks-duplicate': 'hunk-accounting',
        'hunks-stale-head-id': 'hunk-accounting', 'hunks-unknown-item': 'hunk-accounting',
        'hunks-empty-unrelated': 'hunk-accounting', 'response-forged-digest': 'response-binding',
        'response-missing-fail': 'response-items', 'response-only-first-sibling': 'sibling-sweep',
        'response-blank-siblings': 'sibling-sweep', 'closure-only-first-site': 'closure-siblings',
        'closure-missing-fail': 'closure-items', 'closure-open-as-pass': 'closure-verdict',
        'closure-wrong-digest': 'closure-binding', 'closure-regression-as-pass': 'closure-verdict',
        'closure-hunk-claim-as-pass': 'closure-verdict', 'round3-anonymous': 'round-budget',
        'round3-invented-id': 'round-budget', 'round3-no-evidence': 'round-budget',
        'ledger-digest-tamper': 'ledger-integrity', 'ledger-count-tamper': 'ledger-integrity',
        'ledger-self-asserted-acceptance': 'ledger-guards', 'ledger-unexecuted-pass-forged': 'ledger-guards',
        'extra-round-false-open-claim': 'escape-evidence', 'extra-round-false-integrity-claim': 'escape-evidence',
        'closure-anonymous-escape': 'escape-id', 'binding-missing-suite-status': 'binding',
        'portability-nested-consumer-reference': 'portability',
    }
    right_reason = name not in expected_tags or f'[{expected_tags[name]}]' in str(result)
    if actual == good and right_reason:
        passed += 1
        print(f'ok   {name} ({"ok" if good else "fail"})')
    else:
        failed += 1
        print(f'NOT OK {name}: expected {good}, got {result}')


def cmd(*args, cwd=None, env=None):
    return subprocess.run(list(map(str, args)), cwd=cwd, env=env, capture_output=True, text=True)


def git(repo, *args):
    p = cmd('git', '-C', repo, *args)
    if p.returncode:
        raise ValueError(p.stderr)
    return p.stdout.strip()


def inventory(repo, base, head):
    accounting = '\n'.join(f'- {path} — READ — changed surface' for path in git(repo, 'diff', '--no-renames', '--name-only', base, head).splitlines())
    text = f'''# Round 1 review inventory
## Binding
- repository: {repo}
- base_sha: {base}
- head_sha: {head}
- basis: DIFF_ONLY
- scope: COMPLETE
- full_suite: UNKNOWN
- required_platforms: current host
- unavailable_evidence: none
## File accounting
{accounting}
## Inventory
'''
    for n in range(1, 11):
        text += f'''### G-{n:02} — behavior {n}
- kind: portable-class
- source: portable class G{n}
- impact: BLOCKER
- must_hold: input retains its meaning
- applies_to: both readers
- status: {"FAIL" if n == 1 else "PASS"}
- applicable_sites: a.txt:1, b.txt:1
- failing_sites: {"a.txt:1" if n == 1 else "none"}
- evidence: inspected both readers and compared output
- reproduction: run the focused reader test
- class_sweep: searched both reader definitions and callers
- dismissed_sites: none
- closure: both readers retain the input
- catalog_candidate: none
'''
    return text + '''## Routed exclusions encountered
- none
## Verdict
- enumeration: COMPLETE
- verification: COMPLETE
- verdict: BLOCK
'''


def response(inv, repo, head1, head2):
    mapping = hunk_markdown(hunks(repo, head1, head2)).replace('<item ID or UNRELATED: explanation>', 'G-01')
    return f'''# Remediation response
- inventory_sha256: {digest(inv.encode())}
- round1_head_sha: {head1}
- remediation_head_sha: {head2}
## G-01
- disposition: FIXED
- changed_sites: a.txt:1
- applicable_siblings_checked: a.txt:1, b.txt:1
- implementation: retain the input
- tests_added_or_changed: reader test
- commands_and_results: reader test passed
- remaining_limitations: none
## Touched PASS/N/A items
- none
## Remediation hunk accounting
{mapping}
## New interfaces or behavior
- none
'''


def closure(inv, h1, h2):
    return f'''# Round 2 closure review
## Binding
- inventory_sha256: {digest(inv.encode())}
- integrity: VERIFIED
- round1_head_sha: {h1}
- remediation_head_sha: {h2}
- ancestry: VERIFIED
- round1_scope: COMPLETE
## Response and hunk accounting
- response_items_missing: none
- remediation_hunks_unexplained: none
- touched_PASS_or_NA_items: none
## Closure
### G-01 — CLOSED
- sites_verified: a.txt:1, b.txt:1
- reproduction_result: correct output at both sites
- tests: reader test passed
- response_assessment: independently checked implementation
- remaining_failure: none
## Remediation regressions
- none
## Protocol escapes
- none
## Verdict
PASS
'''


def events(path, text):
    path.write_text('\n'.join(json.dumps(e) for e in [
        {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'cat a.txt b.txt'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}},
        {'type': 'turn.completed'}]) + '\n')


with tempfile.TemporaryDirectory(prefix='review-tests-') as temp:
    t = Path(temp)
    repo = t / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    for i in range(3):
        (repo / 'a.txt').write_text(f'a{i}\n' + 'context\n' * 20 + f'end{i}\n')
        (repo / 'b.txt').write_text(f'b{i}\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', f'c{i}')
    base, h1, h2 = [git(repo, 'rev-parse', ref) for ref in ('HEAD~2', 'HEAD~1', 'HEAD')]
    inv = inventory(repo, base, h1)
    res = response(inv, repo, h1, h2)
    close = closure(inv, h1, h2)
    sha = digest(inv.encode())
    ci = lambda text, expected=(): check_inventory(text, repo, base, h1, expected)
    cr = lambda text: check_response(text, inv, repo, h1, h2, sha)
    cc = lambda text: check_closure(text, inv, h2, sha)
    check('binding-missing-suite-status', False, lambda: ci(inv.replace('- full_suite: UNKNOWN\n', '')))
    check('enumeration-complete', True, lambda: ci(inv))
    # A reviewer writes the sha in backticks and says how it verified it, and writes the basis then
    # names its sources. Measured: a binding whose base and head were character-for-character the
    # sealed values was rejected for naming neither. A line naming two shas stays refused -- that one
    # is genuinely ambiguous.
    check('binding-sha-through-markup', True, lambda: ci(inv
        .replace(f'- base_sha: {base}', f'- base_sha: `{base}` (verified: git rev-parse)')
        .replace('- basis: DIFF_ONLY', '- basis: DIFF_ONLY (issue body; contracts at head)')))
    check('binding-two-shas-refused', False, lambda: ci(inv
        .replace(f'- base_sha: {base}', f'- base_sha: `{base}` or maybe `{h2}`')))
    # Underscore is markdown emphasis and also a character these values contain. Stripping it turned
    # DIFF_ONLY into DIFFONLY and made every binding invalid; the verdict axes carry no underscore, so
    # the fault sat latent until a field that does was read through the same helper.
    check('binding-underscored-value-survives', True, lambda: ci(inv
        .replace('- basis: DIFF_ONLY', '- basis: **DIFF_ONLY**')))
    check('enumeration-multiline-site-sweep', True, lambda: ci(inv.replace(
        '- class_sweep: searched both reader definitions and callers',
        '- class_sweep:\n  searched both reader definitions\n  and callers')))
    check('conflicting-fields-rejected', False, lambda: ci(inv.replace('- scope: COMPLETE', '- scope: COMPLETE\n- scope: INCOMPLETE')))
    # A rename is one line naming two changed files; both must count, or the seal asks about a
    # file the reviewer did account for. The reason after the status is prose: a file merely
    # mentioned there is not an accounting claim, and counting it would let silence pass as
    # coverage through the back door.
    check('accounting-rename-pair-counted', True, lambda: ci(inv.replace(
        '- a.txt — READ — changed surface\n- b.txt — READ',
        '- `a.txt` \u2192 `b.txt` — READ')))
    check('accounting-reason-mention-not-counted', False, lambda: ci(inv.replace(
        '- b.txt — READ', '- a.txt — READ_DIFF_ONLY — also looked at b.txt')))
    check('identical-restatement-accepted', True, lambda: ci(inv.replace('- scope: COMPLETE', '- scope: COMPLETE\n- scope: COMPLETE')))
    check('enumeration-missing-default', False, lambda: ci(inv.replace('### G-10', '### P-10')))
    check('enumeration-missing-project-class', False, lambda: ci(inv, ['P-01']))
    check('enumeration-not-read-as-complete', False, lambda: ci(inv.replace('b.txt — READ', 'b.txt — NOT_READ')))
    check('enumeration-duplicate-id', False, lambda: ci(inv.replace('### G-10', '### G-09')))
    check('enumeration-wrong-head', False, lambda: ci(inv.replace(h1, h2)))
    check('enumeration-unknown-status', False, lambda: ci(inv.replace('- status: PASS', '- status: READY')))
    check('enumeration-placeholder-evidence', False, lambda: ci(inv.replace('- evidence: inspected both readers and compared output', '- evidence: <inspection>')))
    check('enumeration-blank-pass-sweep', False, lambda: ci(inv.replace('- class_sweep: searched both reader definitions and callers', '- class_sweep: none')))
    check('na-class-name-is-not-reason', False, lambda: ci(inv.replace('- status: PASS', '- status: N/A').replace('- evidence: inspected both readers and compared output', '- evidence: none')))
    check('noted-needs-dismissed-site', False, lambda: ci(inv.replace('- status: PASS', '- status: NOTED')))
    check('response-all-hunks', True, lambda: cr(res))
    rows = hunks(repo, h1, h2)
    check('hunks-two-sites-same-file', True, lambda: len([r for r in rows if r['path'] == 'a.txt']) == 2)
    first = rows[0]['id']
    line = next(l for l in res.splitlines() if l.startswith('- ' + first))
    check('hunks-missing-one', False, lambda: cr(res.replace(line, '')))
    check('hunks-duplicate', False, lambda: cr(res.replace(line, line + '\n' + line)))
    check('hunks-stale-head-id', False, lambda: cr(res.replace(first, 'H-' + '0' * 20)))
    check('hunks-unknown-item', False, lambda: cr(res.replace('— G-01', '— O-99')))
    check('hunks-unrelated-explanation', True, lambda: bool(cr(res.replace('— G-01', '— UNRELATED: separate feature'))))
    check('hunks-empty-unrelated', False, lambda: cr(res.replace('— G-01', '— UNRELATED: ')))
    check('response-forged-digest', False, lambda: cr(res.replace(sha, '0' * 64)))
    check('response-missing-fail', False, lambda: cr(res.replace('## G-01', '## G-02')))
    check('response-only-first-sibling', False, lambda: cr(res.replace('- applicable_siblings_checked: a.txt:1, b.txt:1', '- applicable_siblings_checked: a.txt:1')))
    check('response-blank-siblings', False, lambda: cr(res.replace('- applicable_siblings_checked: a.txt:1, b.txt:1', '- applicable_siblings_checked: none')))
    check('closure-supported-pass', True, lambda: cc(close))
    check('closure-missing-fail', False, lambda: cc(close.replace('### G-01', '### G-02')))
    check('closure-open-as-pass', False, lambda: cc(close.replace('— CLOSED', '— OPEN')))
    check('closure-only-first-site', False, lambda: cc(close.replace('- sites_verified: a.txt:1, b.txt:1', '- sites_verified: a.txt:1')))
    check('closure-empty-sites', False, lambda: cc(close.replace('- sites_verified: a.txt:1, b.txt:1', '- sites_verified: none')))
    check('closure-wrong-digest', False, lambda: cc(close.replace(sha, '0' * 64)))
    check('closure-escape-without-evidence', False, lambda: cc(close.replace('## Protocol escapes\n- none', '## Protocol escapes\n- ROUND1-ESCAPE G-02').replace('\nPASS\n', '\nBLOCK\n')))
    check('closure-anonymous-escape', False, lambda: cc(close.replace('## Protocol escapes\n- none', '## Protocol escapes\n- ROUND1-ESCAPE: missed input failure').replace('\nPASS\n', '\nBLOCK\n')))
    check('extra-round-false-open-claim', False, lambda: check_extra_round('- G-01 — OPEN — still broken', inv, close, 2, True, False))
    check('extra-round-false-integrity-claim', False, lambda: check_extra_round('- G-01 — INTEGRITY — bad receipt', inv, close, 2, True, False))
    check('closure-regression-as-pass', False, lambda: cc(close.replace('## Remediation regressions\n- none', '## Remediation regressions\n- R-01: introduced a reader failure')))
    check('closure-hunk-claim-as-pass', False, lambda: cc(close.replace('- remediation_hunks_unexplained: none', '- remediation_hunks_unexplained: H-1')))
    check('round3-named-escape', True, lambda: escape_ids('- G-01 — OPEN — reader still fails at the sibling', inv))
    check('round3-anonymous', False, lambda: escape_ids('one more review', inv))
    check('round3-invented-id', False, lambda: escape_ids('- O-99 — OPEN — reader still fails', inv))
    check('round3-no-evidence', False, lambda: escape_ids('- G-01 — OPEN — none', inv))

    check('extra-round-restart-carries-sealed-reason', True, lambda: check_extra_round(
        '- G-01 — SCOPE-CHANGE — closing the replacement inventory', inv, inv, 1, True, False,
        '- G-01 — SCOPE-CHANGE — prior restart followed changed functionality'))

    # Special git changes must not disappear from the accounting surface.
    (repo / 'space name.txt').write_text('new\n')
    (repo / 'binary.bin').write_bytes(b'\0new')
    (repo / 'empty').touch()
    (repo / 'b.txt').rename(repo / 'renamed.txt')
    (repo / 'a.txt').chmod(0o755)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'special changes')
    special = git(repo, 'rev-parse', 'HEAD')
    special_rows = hunks(repo, h2, special)
    for path in ('space name.txt', 'binary.bin', 'empty', 'b.txt', 'renamed.txt', 'a.txt'):
        check('hunks-special-' + path.replace(' ', '-'), True, lambda path=path: any(r['path'] == path for r in special_rows))
    (repo / 'binary.bin').write_bytes(b'\0later')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'later binary')
    stale = response(inv, repo, h1, special)
    check('hunks-binary-change-invalidates-map', False,
          lambda: check_response(stale, inv, repo, h1, git(repo, 'rev-parse', 'HEAD'), sha))

    check('ledger-counts-remediation-regressions', True, lambda: ledger.statistics(close.replace('## Remediation regressions\n- none', '## Remediation regressions\n- R-01 — changed reader now rejects valid input'), 2)['fail_count'] == 1)

    # End-to-end: ledger numbers survive BLOCK, preflight failures, and scope restarts.
    env = dict(os.environ, REVIEW_ARTIFACTS=str(t / 'artifacts'), REVIEW_STUB=str(t / 'events'),
               REVIEW_RESPONSE=str(t / 'response'), PYTHONDONTWRITEBYTECODE='1')
    for key in ('REVIEW_ESCAPES', 'REVIEW_CATALOG', 'REVIEW_EXPECTED_IDS'):
        env.pop(key, None)
    (t / 'response').write_text(res)
    events(t / 'events', inv)
    def host(phase, head, pr='17', environment=env):
        return cmd(SCRIPTS / 'review-round.sh', phase, repo, head, pr, base, 'stub', env=environment)
    # A retry after rejections is round 1 happening, not an escape from it. Measured on a real PR:
    # two rounds this harness rejected for shape took the counter to 3, and the budget then demanded
    # escape IDs naming items in an inventory that was never accepted. The gate had locked itself out
    # of its own first round, and the only way through would have been to invent the IDs.
    reject = dict(env, REVIEW_STUB=str(t / 'bad-events'))
    events(t / 'bad-events', inv.replace('\n## Verdict\n', '\n## Not a verdict\n'))
    def rejected(head, pr):
        return cmd(SCRIPTS / 'review-round.sh', '1', repo, head, pr, base, 'stub', env=reject)
    check('host-rejected-round-is-not-a-round-1', True,
          lambda: (rejected(h1, '31').returncode != 0 and rejected(h1, '31').returncode != 0
                   and 'round-budget' not in cmd(SCRIPTS / 'review-round.sh', '1', repo, h1, '31',
                                                 base, 'stub', env=env).stderr))
    # The same rule lives twice: once before a round runs, once when the ledger is audited. Fixing
    # only the first left the second refusing every audit of a chain whose early rounds were all
    # rejected -- a class-local repair, in the harness built to stop them.
    rejected_root = Path(cmd(SCRIPTS / 'review-round.sh', 'path', repo, h1, '31', base,
                             'stub', env=env).stdout.strip())
    check('audit-of-rejected-rounds-is-not-a-budget-error', True,
          lambda: bool(ledger.audit(rejected_root, repo)))
    r1 = host('1', h1)
    root = Path(host('path', h1).stdout.strip())
    check('host-block-exits-nonzero', True, lambda: r1.returncode != 0)
    check('host-block-inventory-sealed', True, lambda: ledger.audit(root, repo)[1][1]['accepted'])
    events(t / 'events', close.replace('— CLOSED', '— OPEN').replace('\nPASS\n', '\nBLOCK\n'))
    r2 = host('2', h2)
    check('host-stub-never-authorizes-merge', True, lambda: r2.returncode != 0)
    check('host-closure-passes-guards', True, lambda: ledger.audit(root, repo)[1][2]['accepted'])
    check('host-round3-without-escape-blocked', True, lambda: host('2', h2).returncode != 0 and not ledger.read(root)[-1]['executed'])
    (t / 'escapes').write_text('- G-01 — OPEN — previous review missed the sibling reproduction\n')
    named = dict(env, REVIEW_ESCAPES=str(t / 'escapes'))
    host('2', h2, environment=named)
    check('host-round-number-not-reset', True, lambda: len(ledger.audit(root, repo)[0]) == 4)
    check('host-round-report-has-rate', True, lambda: 'escape rate:' in host('report', h2).stdout)
    restarted = inventory(repo, base, special)
    events(t / 'events', restarted)
    (t / 'escapes').write_text('- G-01 — SCOPE-CHANGE — changed head needs a replacement inventory\n')
    host('1', special, environment=named)
    check('host-scope-restart-keeps-round-number', True, lambda: ledger.audit(root, repo)[0][5]['phase'] == 1 and ledger.audit(root, repo)[1][5]['accepted'])
    (t / 'response').write_text(response(restarted, repo, special, special))
    events(t / 'events', closure(restarted, special, special))
    host('2', special, environment=named)
    check('host-restarted-inventory-can-close', True, lambda: ledger.audit(root, repo)[1][6]['accepted'])
    (t / 'response').write_text(res)
    original = root / 'round-0001' / 'ARTIFACT.md'
    saved = original.read_bytes()
    original.write_bytes(saved + b'\nchanged\n')
    check('ledger-digest-tamper', False, lambda: ledger.audit(root, repo))
    original.write_bytes(saved)
    ledger_path = root / 'ledger.jsonl'
    saved_ledger = ledger_path.read_bytes()
    ledger_path.write_bytes(saved_ledger.replace(b'"fail_count":1', b'"fail_count":0', 1))
    check('ledger-count-tamper', False, lambda: ledger.audit(root, repo))
    ledger_path.write_bytes(saved_ledger)
    # Even re-hashing the JSON chain cannot make a false guard result true.
    records = ledger.read(root)
    records[1]['accepted'] = False
    ledger_path.unlink()
    for record in records:
        ledger.append(root, record)
    check('ledger-self-asserted-acceptance', False, lambda: ledger.audit(root, repo))
    ledger_path.write_bytes(saved_ledger)
    records = ledger.read(root)
    records[-1].update(executed=False, accepted=True, verdict='PASS')
    ledger_path.unlink()
    for record in records:
        ledger.append(root, record)
    check('ledger-unexecuted-pass-forged', False, lambda: ledger.audit(root, repo))
    ledger_path.write_bytes(saved_ledger)
    # A receipt written under a different version of the protocol cannot be held to today's guard
    # results: correcting a guard changes them, and eight corrections in one afternoon would
    # otherwise condemn every earlier round in a real PR's chain. The way out of that is to delete
    # the ledger, which destroys the round history it exists to keep. What survives a version move
    # is the artifact hashes and the receipt's own internal consistency -- so a receipt that claims
    # acceptance its own recorded guards do not support is still refused, whatever version wrote it.
    # Simulate what a corrected guard actually leaves behind: a recorded result today's code no
    # longer reproduces, with the receipt's own accept/reject logic still intact.
    records = ledger.read(root)
    for record in records:
        if record.get('event') == 'started':
            record['skill_sha256'] = '0' * 64
        if record.get('event') == 'finished' and record.get('guards'):
            record['guards'] = record['guards'] + [{'guard': 'retired-check', 'ok': True}]
    ledger_path.unlink()
    for record in records:
        ledger.append(root, record)
    # The version a receipt records must cover the code that judged it. SKILL.md alone did not:
    # eight guard corrections moved no byte of the prose, so every receipt still claimed the same
    # version and audit read the corrections as forgeries. A fingerprint that misses the guards
    # cannot tell an upgrade from tampering, which is the only question it is asked.
    guard_file = SCRIPTS / 'lib/guards.sh'
    original_guard = guard_file.read_bytes()
    before = protocol.protocol_sha256(SCRIPTS)
    try:
        guard_file.write_bytes(original_guard + b'\n# a corrected guard\n')
        check('protocol-version-covers-the-guards', True,
              lambda: protocol.protocol_sha256(SCRIPTS) != before)
    finally:
        guard_file.write_bytes(original_guard)
    check('protocol-version-restored', True, lambda: protocol.protocol_sha256(SCRIPTS) == before)
    check('ledger-other-version-audits', True, lambda: bool(ledger.audit(root, repo)))
    records = ledger.read(root)
    for record in records:
        if record.get('event') == 'finished' and record.get('executed'):
            record['accepted'] = not all(c['ok'] for c in record['guards'])
    ledger_path.unlink()
    for record in records:
        ledger.append(root, record)
    check('ledger-other-version-still-checks-itself', False, lambda: ledger.audit(root, repo))
    ledger_path.write_bytes(saved_ledger)
    events(t / 'events', inv)
    host('1', h1, '18')
    (t / 'response').write_text(res.replace(line, ''))
    blocked = host('2', h2, '18')
    check('host-unmapped-hunk-prevents-reviewer', True, lambda: 'hunk-accounting' in blocked.stderr and blocked.returncode != 0)
    (t / 'response').write_text(res.replace('— G-01', '— UNRELATED: separate feature'))
    blocked = host('2', h2, '19')
    # First bind this independent PR, then test the unrelated mapping.
    host('1', h1, '20')
    blocked = host('2', h2, '20')
    check('host-unrelated-is-scope-restart', True, lambda: 'scope-change' in blocked.stderr and blocked.returncode != 0)
    (t / 'response').write_text(res)
    events(t / 'events', inv)
    host('1', h1, '21')
    (t / 'events').write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': close}}) + '\n')
    blocked = host('2', h2, '21')
    check('host-truncated-result-not-evidence', True, lambda: 'guard_turn_completed' in blocked.stderr and blocked.returncode != 0)

    # Inventory digests cover bytes, including CRLF; parsing must not reseal normalized text.
    crlf = inv.replace('\n', '\r\n')
    events(t / 'events', crlf)
    host('1', h1, '23')
    (t / 'response').write_text(res.replace(sha, digest(crlf.encode())))
    events(t / 'events', close.replace(sha, digest(crlf.encode())))
    host('2', h2, '23')
    crlf_root = Path(host('path', h2, '23').stdout.strip())
    check('host-inventory-seals-exact-crlf-bytes', True, lambda: ledger.audit(crlf_root, repo)[1][2]['accepted'])
    (t / 'response').write_text(res)

    # A final prose message must not resurrect an earlier inventory.
    events(t / 'events', inv)
    with (t / 'events').open('a') as f:
        f.write(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Unable to finish'}}) + '\n')
    check('extract-does-not-resurrect-draft', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/extract.py', t / 'events', '# Round 1 review inventory').returncode != 0)
    (t / 'events').write_text(json.dumps({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True}) + '\n')
    check('executor-error-result-rejected', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'completed', t / 'events').returncode != 0)
    (t / 'events').write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"type":"command_execution"}'}}) + '\n')
    check('executor-prose-is-not-tool-execution', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'commands', t / 'events').returncode != 0)

    (t / 'events').write_text('{"type":"turn.completed"}\n{"type":"turn.started"}\n')
    check('executor-earlier-turn-not-completion', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'completed', t / 'events').returncode != 0)

    # Exercise the consumer adapter without network; its remote is our own repository.
    git(repo, 'remote', 'add', 'origin', str(repo))
    fakebin = t / 'bin'
    fakebin.mkdir()
    (fakebin / 'gh').write_text('#!/bin/sh\ncat "$TEST_PR_METADATA"\n')
    (fakebin / 'gh').chmod(0o755)
    metadata = t / 'metadata.json'
    metadata.write_text(json.dumps({'number': 42, 'headRefOid': h1, 'baseRefOid': base, 'url': 'fixture'}))
    prenv = dict(env, PATH=str(fakebin) + os.pathsep + env['PATH'], TEST_PR_METADATA=str(metadata))
    events(t / 'events', inv)
    def pr():
        return cmd(SCRIPTS / 'review-pr.sh', repo, '42', 'auto', 'stub', env=prenv)
    check('consumer-real-protocol-called', True, lambda: 'round 1, phase 1' in pr().stderr)
    check('consumer-same-head-no-repeat', True, lambda: 'round 2, phase' not in pr().stderr)
    metadata.write_text(json.dumps({'number': 42, 'headRefOid': h2, 'baseRefOid': base, 'url': 'fixture'}))
    (t / 'response').write_text(res)
    events(t / 'events', close)
    check('consumer-remediation-routes-to-closure', True, lambda: 'round 2, phase 2' in pr().stderr)
    check('consumer-stub-pass-never-merge-success', True, lambda: pr().returncode != 0)

    # Install the actual hook in a small repository. Its independently installed test
    # fixture rejects a broken probe even when the staged suite is replaced with exit 0.
    hookrepo = t / 'hookrepo'
    hookrepo.mkdir()
    git(hookrepo, 'init', '-q')
    git(hookrepo, 'config', 'user.name', 'test')
    git(hookrepo, 'config', 'user.email', 'test@example.invalid')
    candidate = hookrepo / 'skills/sol-simplify-review/scripts'
    candidate.mkdir(parents=True)
    (candidate / 'selftest.sh').write_text('#!/bin/sh\nexit 0\n')
    (candidate / 'probe.sh').write_text('#!/bin/sh\necho reject\n')
    git(hookrepo, 'add', '.')
    git(hookrepo, 'commit', '-qm', 'seed')
    installed = cmd(SCRIPTS / 'install-hook.sh', hookrepo)
    check('hook-installs', True, lambda: installed.returncode == 0)
    trusted = hookrepo / '.git/hooks/sol-simplify-review'
    (trusted / 'scripts/selftest.sh').write_text('#!/bin/sh\nset -eu\n[ "$(bash "$REVIEW_TEST_SCRIPTS/probe.sh")" = reject ] || { echo "NOT OK missing-input-was-accepted"; exit 1; }\n')
    # Consumer identities from the maintainer's installed snapshot still apply, if any.
    (candidate / 'probe.sh').write_text('#!/bin/sh\necho accept\n')
    git(hookrepo, 'add', '.')
    blocked = cmd('git', '-C', hookrepo, 'commit', '-qm', 'broken guard')
    check('hook-candidate-cannot-self-pass', True, lambda: blocked.returncode != 0 and 'missing-input-was-accepted' in blocked.stderr)
    (candidate / 'probe.sh').write_text('#!/bin/sh\necho reject\n')
    blocked = cmd('git', '-C', hookrepo, 'commit', '-qm', 'unstaged fix')
    check('hook-tests-staged-not-working-tree', True, lambda: blocked.returncode != 0 and 'missing-input-was-accepted' in blocked.stderr)
    git(hookrepo, 'add', '.')
    (candidate / 'selftest.sh').write_text('#!/bin/sh\necho "NOT OK candidate failure"\nexit 1\n')
    git(hookrepo, 'add', '.')
    blocked = cmd('git', '-C', hookrepo, 'commit', '-qm', 'failing new test')
    check('hook-candidate-failure-blocks-commit', True, lambda: blocked.returncode != 0 and 'candidate failure' in blocked.stderr)
    (candidate / 'selftest.sh').write_text('#!/bin/sh\nexit 0\n# changed\n')
    git(hookrepo, 'add', '.')
    check('hook-valid-snapshot-commits', True, lambda: cmd('git', '-C', hookrepo, 'commit', '-qm', 'fixed').returncode == 0)
    (trusted / 'scripts/selftest.sh').write_text('#!/bin/sh\nexit 1\n')
    (hookrepo / 'unrelated.txt').write_text('product edit\n')
    git(hookrepo, 'add', '.')
    check('hook-unrelated-work-not-gated', True, lambda: cmd('git', '-C', hookrepo, 'commit', '-qm', 'product').returncode == 0)

    config = t / 'consumers.json'
    config.write_text(json.dumps({'consumers': [{'repository': '/example/fixture-consumer', 'markers': ['FixtureAlias']}]}))
    portable = t / 'portable'
    portable.mkdir()
    (portable / 'SKILL.md').write_text('generic review')
    check('portability-clean', True, lambda: portability(portable, config))
    (portable / 'nested').mkdir()
    (portable / 'nested' / 'script.sh').write_text('FixtureAlias')
    check('portability-nested-consumer-reference', False, lambda: portability(portable, config))
    actual_config = os.environ.get('REVIEW_CONSUMERS_CONFIG')
    default = SCRIPTS.parents[2] / 'dogfood/consumers.json'
    if actual_config or default.exists():
        check('portability-whole-skill', True, lambda: portability(SCRIPTS.parent, actual_config or default))

print(f'protocol-selftest: {passed} passed, {failed} failed')
sys.exit(bool(failed))
