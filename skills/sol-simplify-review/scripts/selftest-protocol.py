#!/usr/bin/env python3
"""Offline execution, evidence handoff, failure witnesses and consumer adapter tests."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile

SCRIPTS = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SCRIPTS / 'lib'))
import ledger
import protocol
import catalog
from protocol import Rejected, digest, hunks
from portability import check as portability

passed = failed = 0


def check(name, good, fn, tag=None):
    global passed, failed
    try:
        result = fn()
        actual = result is not False
    except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        actual, result = False, str(e)
    if actual == good and (tag is None or f'[{tag}]' in str(result)):
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


def events(path, text, tools=True, complete=True):
    rows = []
    if tools:
        rows.append({'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'cat a.txt b.txt'}})
    rows.append({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}})
    if complete:
        rows.append({'type': 'turn.completed'})
    path.write_text('\n'.join(json.dumps(e) for e in rows) + '\n')


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
        git(repo, 'add', 'a.txt', 'b.txt')
        git(repo, 'commit', '-qm', f'c{i}')
    base, h1, h2 = [git(repo, 'rev-parse', ref) for ref in ('HEAD~2', 'HEAD~1', 'HEAD')]
    env = {k: v for k, v in os.environ.items() if not k.startswith('REVIEW_')}
    env.update(REVIEW_ARTIFACTS=str(t / 'artifacts'), REVIEW_STUB=str(t / 'events'),
               PYTHONDONTWRITEBYTECODE='1')
    def host(phase, head=h1, pr='17', environment=env, target=base):
        return cmd(SCRIPTS / 'review-round.sh', phase, repo, head, pr, target, 'stub', env=environment)
    def root_for(pr='17'):
        return Path(host('path', pr=pr).stdout.strip())
    original = '# Round 1 review inventory\nF-1 BLOCKER: a.txt:2 fails inside a.txt:1-3.\nThe b.txt sibling is checked. Fix the reader.\n'
    events(t / 'events', original)
    r1 = host('1')
    root = root_for()
    check('prose-recorded-without-inventory-envelope', True, lambda: r1.returncode == 10 and ledger.audit(root, repo)[1][1]['recorded'])
    check('prose-recorded-is-never-merge-success', True, lambda: r1.returncode != 0)
    check('original-bytes-preserved', True, lambda: (root / 'round-0001/ARTIFACT.md').read_bytes() == original.encode())
    check('receipt-has-no-invented-verdict-or-count', True,
          lambda: not ({'accepted', 'verdict', 'item_count', 'fail_count'} & ledger.read(root)[-1].keys()))
    # Neither syntactic PASS nor tools plus a vacuous PASS can authorize a merge.
    for n, text in enumerate(['PASS', '{"verdict":"approve","findings":[]}', 'TBD: gathering evidence'], 1):
        events(t / 'events', text)
        check(f'empty-envelope-never-approval-{n}', True, lambda n=n: host('1', pr=f'empty{n}').returncode == 10)
    check('review-exit-has-no-success-branch', True,
          lambda: protocol.review_exit(True) == 10 and protocol.review_exit(False) == 5)
    events(t / 'events', 'PASS', tools=False)
    failed_run = host('1', pr='no-tools')
    check('no-tools-fails-for-tool-evidence', True, lambda: failed_run.returncode == 5 and '[guard_cmds_nonzero]' in failed_run.stderr)
    events(t / 'events', 'BLOCK F-1', complete=False)
    failed_run = host('1', pr='truncated')
    check('truncated-stream-fails-for-completion', True, lambda: failed_run.returncode == 5 and '[guard_turn_completed]' in failed_run.stderr)
    events(t / 'events', '   ')
    failed_run = host('1', pr='empty-final')
    check('empty-final-fails-for-last-message', True, lambda: failed_run.returncode == 5 and '[last-message]' in failed_run.stderr)
    check('followup-with-no-original-refused', True, lambda: '[handoff]' in host('2', h2, 'absent').stderr)
    events(t / 'events', 'F-1 CLOSED after the reader reproduction. F-2 OPEN: the repair breaks the sibling.')
    r2 = host('2', h2)
    check('followup-needs-no-prose-mapping-or-response-gate', True, lambda: r2.returncode == 10)
    check('followup-binds-original', True, lambda: (root / 'round-0002/ROUND1_INVENTORY.md').read_bytes() == original.encode())
    check('followup-has-complete-remediation-diff', True,
          lambda: (root / 'round-0002/REMEDIATION.patch').read_bytes() == protocol.git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', h1, h2))
    events(t / 'events', 'F-2 CLOSED. Required tests passed. PASS recommendation for maintainer review.')
    r3 = host('2', h2)
    check('third-attempt-needs-no-escape-form', True, lambda: r3.returncode == 10 and '[round-budget]' not in r3.stderr)
    check('later-open-finding-carried-forward', True,
          lambda: 'F-2 OPEN' in (root / 'round-0003/PREVIOUS_REVIEW.md').read_text())
    check('pass-followup-never-merge-success', True, lambda: r3.returncode != 0)
    check('round-numbers-survive-followup', True, lambda: len(ledger.audit(root, repo)[0]) == 3)
    check('changed-base-needs-scope-review', True, lambda: '[scope-change]' in host('2', h2, target=h1).stderr)
    check('backwards-remediation-refused', True, lambda: '[ancestry]' in host('2', base).stderr)
    events(t / 'events', original)
    check('invalid-base-refused', True, lambda: '[ancestry]' in host('1', base, 'badbase', target=h2).stderr)
    (t / 'response').write_text('F-1: repaired both readers. Focused tests passed.')
    events(t / 'events', 'Follow-up with a response, still a recommendation only.')
    check('prose-response-is-carried', True, lambda: host('2', h2, environment=dict(env, REVIEW_RESPONSE=str(t / 'response'))).returncode == 10)
    check('report-does-not-claim-escape-rate', True,
          lambda: 'Safe merge completion is not measured' in host('report').stdout and 'escape rate:' not in host('report').stdout)
    check('report-does-not-create-evidence', True,
          lambda: host('report', pr='unobserved').returncode == 0 and not root_for('unobserved').exists())
    (root / '.lock').chmod(0o444)
    root.chmod(0o555)
    try:
        check('report-reads-protected-evidence', True, lambda: host('report').returncode == 0)
        check('hunks-read-protected-evidence', True, lambda: host('hunks', h2).returncode == 0)
    finally:
        root.chmod(0o755)
        (root / '.lock').chmod(0o644)
    # Every integrity check below has a witness with valid surrounding evidence.
    original_path = root / 'round-0001/ARTIFACT.md'
    saved = original_path.read_bytes()
    original_path.write_bytes(saved + b'changed')
    check('ledger-altered-artifact', False, lambda: ledger.audit(root, repo), 'ledger-integrity')
    original_path.write_bytes(saved)
    ledger_path = root / 'ledger.jsonl'
    saved_ledger = ledger_path.read_bytes()
    ledger_path.write_bytes(saved_ledger.replace(b'"recorded":true', b'"recorded":false', 1))
    check('ledger-broken-chain', False, lambda: ledger.audit(root, repo), 'ledger-integrity')
    ledger_path.write_bytes(saved_ledger)
    def rewrite(records):
        ledger_path.unlink()
        for record in records:
            ledger.append(root, record)
    records = ledger.read(root)
    records[1]['recorded'] = False
    rewrite(records)
    check('ledger-false-result-even-with-rehashed-chain', False, lambda: ledger.audit(root, repo), 'ledger-guards')
    ledger_path.write_bytes(saved_ledger)
    records = ledger.read(root)
    records[1]['accepted'] = True
    rewrite(records)
    check('ledger-prose-cannot-claim-acceptance', False, lambda: ledger.audit(root, repo), 'ledger-guards')
    ledger_path.write_bytes(saved_ledger)
    records = ledger.read(root)
    records[1]['executed'] = False
    rewrite(records)
    check('ledger-unexecuted-recorded-result', False, lambda: ledger.audit(root, repo), 'ledger-guards')
    ledger_path.write_bytes(saved_ledger)
    records = ledger.read(root)
    del records[1]['outputs']['ARTIFACT.md']
    rewrite(records)
    check('ledger-missing-output-hash', False, lambda: ledger.audit(root, repo), 'ledger-integrity')
    ledger_path.write_bytes(saved_ledger)
    records = ledger.read(root)
    records[1]['guards'][0]['ok'] = False
    records[1]['recorded'] = False
    rewrite(records)
    check('ledger-same-version-recomputes', False, lambda: ledger.audit(root, repo), 'ledger-guards')
    ledger_path.write_bytes(saved_ledger)
    check('removed-checkout-failure-is-not-forgotten', True,
          lambda: not ledger.evidence_available([{'guard': 'target', 'ok': True}],
              {'executed': True, 'guards': [{'guard': 'seal-location', 'ok': False}]}))
    # Legacy rejections stay rejections; prose-format faults no longer erase their evidence.
    events(t / 'events', original)
    host('1', pr='legacy')
    legacy = root_for('legacy')
    rows = ledger.read(legacy)
    rows[0].pop('mode')
    rows[0]['skill_sha256'] = 'old-version'
    rows[1].pop('recorded')
    rows[1]['accepted'] = False
    rows[1]['guards'].append({'guard': 'inventory', 'ok': False, 'reason': 'GUARD FAIL [sibling-sweep] range differs'})
    (legacy / 'ledger.jsonl').unlink()
    for row in rows:
        ledger.append(legacy, row)
    old_bytes = (legacy / 'ledger.jsonl').read_bytes()
    check('legacy-rejected-prose-available-for-followup', True, lambda: bool(ledger.audit(legacy, repo)[2]))
    check('legacy-refusal-not-rewritten-as-acceptance', True,
          lambda: not ledger.audit(legacy, repo)[1][1]['accepted'] and (legacy / 'ledger.jsonl').read_bytes() == old_bytes)
    events(t / 'events', 'F-1 CLOSED after reproducing the original failure.')
    check('legacy-followup-can-run', True, lambda: host('2', h2, 'legacy').returncode == 10)
    check('leaf-refusal-count', True, lambda: ledger.guard_rejections({1: rows[1]}) == {'sibling-sweep': 1})
    # Same PR repetition and a recurrence assertion remain attributed leads.
    cat_root = t / 'catalog'
    for i in range(2):
        d = cat_root / f'round-{i+1:04}'
        d.mkdir(parents=True)
        (d / 'ARTIFACT.md').write_text('- catalog_candidate: a stuck journal -- recurs again\n')
    leads = catalog.render(catalog.harvest(cat_root))
    check('catalog-no-self-promotion', True, lambda: 'P-01' not in leads and 'mandatory classes' in leads and 'independent changes' in leads)
    check('catalog-keeps-source-rounds', True, lambda: 'round-0001' in leads and 'round-0002' in leads)
    check('catalog-empty-is-none', True, lambda: catalog.render({}) == 'none')
    # Hunk navigation still includes all Git changes, including metadata and rename endpoints.
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
    check('hunks-distinguish-two-sites', True, lambda: len([r for r in hunks(repo, h1, h2) if r['path'] == 'a.txt']) == 2)
    # Exact CRLF and Markdown bytes are preserved, not normalized before sealing.
    crlf = '**BLOCK.**\r\nA durable pending record at `a.txt:1-3`.\r\n'
    events(t / 'events', crlf)
    host('1', pr='crlf')
    check('raw-crlf-final-preserved', True, lambda: (root_for('crlf') / 'round-0001/ARTIFACT.md').read_bytes() == crlf.encode())
    # Exercise the real PR adapter with local Git and a fake metadata provider, no network/model.
    git(repo, 'remote', 'add', 'origin', str(repo))
    fakebin = t / 'bin'
    fakebin.mkdir()
    (fakebin / 'gh').write_text('#!/bin/sh\ncat "$TEST_PR_METADATA"\n')
    (fakebin / 'gh').chmod(0o755)
    metadata = t / 'metadata.json'
    metadata.write_text(json.dumps({'number': 42, 'headRefOid': h1, 'baseRefOid': base, 'url': 'fixture'}))
    prenv = dict(env, PATH=str(fakebin) + os.pathsep + env['PATH'], TEST_PR_METADATA=str(metadata))
    events(t / 'events', original + '- catalog_candidate: retained lead -- recurs\n')
    def pr():
        return cmd(SCRIPTS / 'review-pr.sh', repo, '42', 'auto', 'stub', env=prenv)
    check('consumer-runs-first-review', True, lambda: 'round 1, phase 1' in pr().stderr)
    check('consumer-same-head-no-repeat', True, lambda: 'round 2, phase' not in pr().stderr)
    check('consumer-cache-does-not-authorize', True, lambda: pr().returncode == 10)
    metadata.write_text(json.dumps({'number': 42, 'headRefOid': h2, 'baseRefOid': base, 'url': 'fixture'}))
    events(t / 'events', 'PASS recommendation. F-1 independently checked CLOSED.')
    check('consumer-changed-head-enters-followup', True, lambda: 'round 2, phase 2' in pr().stderr)
    check('consumer-pass-never-merge-success', True, lambda: pr().returncode == 10)
    (t / 'events').write_text('{"type":"result","subtype":"error_during_execution","is_error":true}\n')
    check('executor-error-result-rejected', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'completed', t / 'events').returncode != 0)
    (t / 'events').write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"type":"command_execution"}'}}) + '\n')
    check('executor-prose-is-not-tool-execution', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'commands', t / 'events').returncode != 0)
    (t / 'events').write_text('{"type":"turn.completed"}\n{"type":"turn.started"}\n')
    check('executor-earlier-turn-not-completion', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'completed', t / 'events').returncode != 0)
    # Fingerprint changes cover the code that judges evidence as well as prompt text.
    version = t / 'version'
    shutil.copytree(SCRIPTS, version / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copyfile(SCRIPTS.parent / 'SKILL.md', version / 'SKILL.md')
    before = protocol.protocol_sha256(version / 'scripts')
    with (version / 'scripts/lib/events.py').open('a') as f:
        f.write('\n# changed event interpretation\n')
    check('protocol-version-covers-the-guards', True,
          lambda: protocol.protocol_sha256(version / 'scripts') != before)
    # A candidate-only suite cannot erase installed failure witnesses. Existing hook behavior.
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

    (trusted / 'scripts/retired.py').write_text('obsolete installed source\n')
    check('hook-reinstall-removes-retired-source', True,
          lambda: cmd(SCRIPTS / 'install-hook.sh', hookrepo).returncode == 0
          and not (trusted / 'scripts/retired.py').exists())

    check('hook-can-reinstall-selected-installed-version', True,
          lambda: cmd(trusted / 'scripts/install-hook.sh', hookrepo).returncode == 0
          and (trusted / 'scripts/selftest.sh').is_file())

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
