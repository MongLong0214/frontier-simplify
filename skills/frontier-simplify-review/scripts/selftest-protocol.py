#!/usr/bin/env python3
"""Offline execution, evidence handoff, failure witnesses and consumer adapter tests."""
import json
import io
import importlib.util
import fcntl
import os
import plistlib
import runpy
import shutil
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

SCRIPTS = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SCRIPTS / 'lib'))
import ledger
import protocol
import catalog
import replay
import witness
from protocol import Rejected, digest, hunks, require
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
    # A check that does not exist must not refuse a round. Reported by a consumer whose artifact
    # was BLOCKed by `guard_no_placeholder: command not found` -- a guard removed while a caller
    # still named it, its absence arriving as that guard's own failure text. Absence scored as a
    # finding, inside the harness built to catch that.
    def _raised(fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - the type IS the assertion
            return e
        return None
    check('missing-guard-is-a-harness-error', True,
          lambda: isinstance(_raised(lambda: ledger.shell_guard('guard_that_does_not_exist', '/tmp')),
                             ledger.MissingGuard))
    check('present-guard-still-judges', True,
          lambda: _raised(lambda: ledger.shell_guard('guard_no_seal_in_tree', '/tmp')) is None)
    check('prose-recorded-without-inventory-envelope', True, lambda: r1.returncode == 10 and ledger.audit(root, repo)[1][1]['recorded'])
    check('prose-recorded-is-never-merge-success', True, lambda: r1.returncode != 0)
    check('original-bytes-preserved', True, lambda: (root / 'round-0001/ARTIFACT.md').read_bytes() == original.encode())
    check('seal-stamps-the-started-protocol', True,
          lambda: 'protocol_sha256: ' + ledger.read(root)[0]['context']['protocol_sha256']
          in (root / 'round-0001/SEAL.txt').read_text())
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
    check('third-attempt-ends-in-handoff', True, lambda: r3.returncode == 11 and 'HANDOFF' in r3.stdout)
    check('later-open-finding-carried-forward', True,
          lambda: 'F-2 OPEN' in (root / 'round-0003/PREVIOUS_REVIEW.md').read_text())
    check('pass-followup-never-merge-success', True, lambda: r3.returncode != 0)
    check('round-numbers-survive-followup', True, lambda: len(ledger.audit(root, repo)[0]) == 3)
    limited_bytes = (root / 'ledger.jsonl').read_bytes()
    # Missing stub input would fail if any forbidden invocation reached an executor.
    for phase, head in [('2', h2), ('1', h2), ('1', base)]:
        stopped = host(phase, head, environment=dict(env, REVIEW_STUB=str(t / 'absent-events')))
        check(f'budget-stops-{phase}-{head[:7]}', True,
              lambda: stopped.returncode == 11 and 'HANDOFF' in stopped.stdout
              and (root / 'ledger.jsonl').read_bytes() == limited_bytes
              and not (root / 'round-0004').exists())
    events(t / 'events', 'PASS', tools=False)
    failures = [host('1', pr='failed-budget') for _ in range(3)]
    check('failed-attempts-consume-budget', True,
          lambda: all(p.returncode == 5 for p in failures) and 'HANDOFF' in failures[-1].stdout
          and host('1', pr='failed-budget').returncode == 11)
    interrupted = root_for('interrupted-budget')
    interrupted.mkdir(parents=True)
    for i in range(1, 4):
        ledger.append(interrupted, dict(event='started', round=i, phase=1, head_sha=h1, base_sha=base, inputs={}))
    check('interruptions-consume-budget', True,
          lambda: host('1', pr='interrupted-budget').returncode == 11
          and len(ledger.read(interrupted)) == 3)
    events(t / 'events', original)
    host('1', pr='scope')
    check('changed-base-needs-scope-review', True, lambda: '[scope-change]' in host('2', h2, 'scope', target=h1).stderr)
    check('backwards-remediation-refused', True, lambda: '[ancestry]' in host('2', base, 'scope').stderr)
    events(t / 'events', original)
    check('invalid-base-refused', True, lambda: '[ancestry]' in host('1', base, 'badbase', target=h2).stderr)
    (t / 'response').write_text('F-1: repaired both readers. Focused tests passed.')
    events(t / 'events', 'Follow-up with a response, still a recommendation only.')
    host('1', pr='response')
    check('prose-response-is-carried', True, lambda: host('2', h2, pr='response', environment=dict(env, REVIEW_RESPONSE=str(t / 'response'))).returncode == 10)
    check('report-does-not-claim-escape-rate', True,
          lambda: 'Safe merge completion is not measured' in host('report').stdout and 'escape rate:' not in host('report').stdout)
    check('report-does-not-create-evidence', True,
          lambda: host('report', pr='unobserved').returncode == 0 and not root_for('unobserved').exists())
    reported = host('report')
    check('report-exposes-recorded-runtime-and-finish-freshness', True,
          lambda: ledger.read(root)[0]['skill_sha256'] in reported.stdout
          and 'freshness at finish: FRESH' in reported.stdout)
    progress = io.StringIO()
    real_audit = ledger.audit
    def audit_after_progress(*args, **kwargs):
        require(bool(progress.getvalue()), 'test-progress', 'report stayed silent before auditing')
        return real_audit(*args, **kwargs)
    def report_progress():
        with patch.object(sys, 'stdout', progress), patch.object(ledger, 'audit', audit_after_progress):
            ledger.report(root, repo)
    check('report-announces-evidence-check-before-audit', True, report_progress)
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
    # Replay binds the caller's target, not the most convenient historical successful run.
    replay_out = io.StringIO()
    check('replay-exact-target-evidence-is-not-approval', True,
          lambda: replay.replay(root, repo, base, h2, replay_out) == 10
          and 'No merge authorization' in replay_out.getvalue())
    check('replay-missing-head', False,
          lambda: replay.replay(root_for('empty1'), repo, base, h2, io.StringIO()), 'replay-target')
    check('replay-missing-base', False,
          lambda: replay.replay(root_for('empty1'), repo, h1, h1, io.StringIO()), 'replay-target')
    check('replay-no-ledger', False,
          lambda: replay.replay(t / 'missing-ledger', repo, base, h1, io.StringIO()), 'replay-target')
    check('replay-failed-execution', False,
          lambda: replay.replay(root_for('truncated'), repo, base, h1, io.StringIO()), 'replay-evidence')
    replay_out = io.StringIO()
    check('replay-legacy-refusal-remains-historical', True,
          lambda: replay.replay(legacy, repo, base, h1, replay_out) == 10
          and 'historical_accepted=False' in replay_out.getvalue())
    before_replay = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    root.chmod(0o555)
    try:
        check('replay-readonly-evidence', True,
              lambda: replay.replay(root, repo, base, h2, io.StringIO()) == 10
              and before_replay == {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()})
    finally:
        root.chmod(0o755)
    # An interrupted retry must not inherit the prior attempt's availability.
    saved_ledger = ledger_path.read_bytes()
    next_round = len(ledger.audit(root, repo)[0]) + 1
    ledger.append(root, dict(event='started', round=next_round, phase=2,
                             base_sha=base, head_sha=h2, inputs={}))
    check('replay-latest-interrupted-attempt', False,
          lambda: replay.replay(root, repo, base, h2, io.StringIO()), 'replay-evidence')
    ledger_path.write_bytes(saved_ledger)
    original_path.write_bytes(saved + b'tampered')
    check('replay-altered-artifact', False,
          lambda: replay.replay(root, repo, base, h2, io.StringIO()), 'ledger-integrity')
    original_path.write_bytes(saved)
    check('replay-cli-missing-target-exit', True,
          lambda: cmd('bash', SCRIPTS / 'review-replay.sh', repo, root, base, base).returncode == 5)
    # Rehashing a wrong input does not bind it to Git. All surrounding execution stays valid.
    for name, content, tag in [('DIFF.patch', b'wrong patch\n', 'replay-diff'),
                               ('CHANGED.txt', b'wrong.txt\n', 'replay-changed'),
                               ('base', None, 'replay-base')]:
        binding_root = t / tag
        shutil.copytree(root_for('empty1'), binding_root)
        rows = ledger.read(binding_root)
        requested_base = base
        if name == 'base':
            requested_base = h1
            rows[0]['base_sha'] = h1
        else:
            (binding_root / 'round-0001' / name).write_bytes(content)
            rows[0]['inputs'][name] = digest(content)
        (binding_root / 'ledger.jsonl').unlink()
        for row in rows:
            ledger.append(binding_root, row)
        check(tag + '-rejects-rehashed-substitution', False,
              lambda: replay.replay(binding_root, repo, requested_base, h1, io.StringIO()), tag)
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
    lessons = t / 'lessons'
    (lessons / 'measured').mkdir(parents=True)
    (lessons / 'measured/LEAD.md').write_text('Host-selected reproduced question: check the independently named facet.\n')
    prenv['REVIEW_LESSONS'] = str(lessons)
    def pr():
        return cmd(SCRIPTS / 'review-pr.sh', repo, '42', 'auto', 'stub', env=prenv)
    check('consumer-runs-first-review', True, lambda: 'round 1, phase 1' in pr().stderr)
    check('consumer-same-head-no-repeat', True, lambda: 'round 2, phase' not in pr().stderr)
    check('consumer-cache-does-not-authorize', True, lambda: pr().returncode == 10)
    metadata.write_text(json.dumps({'number': 42, 'headRefOid': h2, 'baseRefOid': base, 'url': 'fixture'}))
    events(t / 'events', 'PASS recommendation. F-1 independently checked CLOSED.')
    check('consumer-changed-head-enters-followup', True, lambda: 'round 2, phase 2' in pr().stderr)
    check('consumer-pass-never-merge-success', True, lambda: pr().returncode == 10)
    consumer_roots = list((t / 'artifacts/consumers').glob('*/repository'))
    mirror = consumer_roots[0]
    consumer_root = Path(cmd(SCRIPTS / 'review-round.sh', 'path', mirror, h2, '42', env=prenv).stdout.strip())
    # Reporting existing receipts needs neither live PR metadata nor a remote fetch, even
    # while another invocation holds the mirror's fetch lock.
    with (mirror.parent / '.lock').open('a') as fetch_lock:
        fcntl.flock(fetch_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        offline_report = cmd(SCRIPTS / 'review-pr.sh', repo, '42', 'report', 'stub',
                             env=dict(prenv, TEST_PR_METADATA=str(t / 'offline-metadata'),
                                      REVIEW_LESSONS=str(t / 'unavailable-lessons')))
    check('consumer-report-is-offline-and-independent-of-fetch-lock', True,
          lambda: offline_report.returncode == 0 and '2 attempts' in offline_report.stdout)
    unseen_report = t / 'report-only'
    offline_empty = cmd(SCRIPTS / 'review-pr.sh', repo, '42', 'report', 'stub',
                        env=dict(prenv, REVIEW_ARTIFACTS=str(unseen_report),
                                 TEST_PR_METADATA=str(t / 'offline-metadata')))
    check('consumer-report-without-history-is-offline-and-readonly', True,
          lambda: offline_empty.returncode == 0 and 'NOT_REVIEWED' in offline_empty.stdout
          and not unseen_report.exists())
    check('replayed-lead-reaches-both-prompt-phases', True,
          lambda: all('check the independently named facet' in (consumer_root / f'round-{n:04}/prompt.txt').read_text()
                      for n in (1, 2)))
    metadata.write_text(json.dumps({'number': 42, 'headRefOid': special, 'baseRefOid': base, 'url': 'fixture'}))
    events(t / 'events', 'F-NEW BLOCKER: the latest repair still breaks a sibling. Required platform unavailable.')
    last = pr()
    check('consumer-third-round-retains-blocker-and-hands-off', True,
          lambda: last.returncode == 11 and 'F-NEW BLOCKER' in (consumer_root / 'round-0003/ARTIFACT.md').read_text())
    metadata.write_text(json.dumps({'number': 42, 'headRefOid': h1, 'baseRefOid': base, 'url': 'fixture'}))
    cached_limit = pr()
    check('consumer-new-head-cannot-reset-budget', True,
          lambda: cached_limit.returncode == 11 and 'round 4, phase' not in cached_limit.stderr
          and len(ledger.audit(consumer_root, mirror)[0]) == 3)
    metadata.write_text(json.dumps({'number': 43, 'headRefOid': h2, 'baseRefOid': base, 'url': 'fixture'}))
    events(t / 'events', original)
    cmd(SCRIPTS / 'review-pr.sh', repo, '43', 'auto', 'stub', env=prenv)
    metadata.write_text(json.dumps({'number': 43, 'headRefOid': h2, 'baseRefOid': h1, 'url': 'fixture'}))
    changed_target = cmd(SCRIPTS / 'review-pr.sh', repo, '43', 'auto', 'stub', env=prenv)
    check('consumer-cache-cannot-hide-base-change', True,
          lambda: changed_target.returncode == 10 and 'round 2, phase 1' in changed_target.stderr)
    metadata.write_text(json.dumps({'number': 43, 'headRefOid': special, 'baseRefOid': h1}))
    changed_target_followup = cmd(SCRIPTS / 'review-pr.sh', repo, '43', 'auto', 'stub', env=prenv)
    check('changed-scope-keeps-budget-and-new-original', True,
          lambda: changed_target_followup.returncode == 11
          and 'round 3, phase 2' in changed_target_followup.stderr)
    missing_lessons = cmd(SCRIPTS / 'review-pr.sh', repo, '43', 'auto', 'stub',
                          env=dict(prenv, REVIEW_LESSONS=str(t / 'missing-lessons')))
    check('consumer-missing-lesson-directory-is-not-empty-evidence', True,
          lambda: missing_lessons.returncode != 10 and '[consumer]' in missing_lessons.stderr
          and 'REVIEW_LESSONS directory is missing' in missing_lessons.stderr)
    # Same code is reusable only under the same caller inputs. Each case gets its own
    # stable PR so the existing budget cannot hide a bad cache hit.
    def consumer(number, environment=prenv, phase='auto', executor='stub'):
        metadata.write_text(json.dumps({'number': number, 'headRefOid': h2,
                                       'baseRefOid': base, 'url': 'fixture'}))
        return cmd(SCRIPTS / 'review-pr.sh', repo, str(number), phase, executor, env=environment)
    consumer(64)
    metadata.write_text(json.dumps({'number': 64, 'headRefOid': h1, 'baseRefOid': base}))
    rewritten = cmd(SCRIPTS / 'review-pr.sh', repo, '64', 'auto', 'stub', env=prenv)
    check('auto-reviews-rewritten-history-without-resetting-budget', True,
          lambda: rewritten.returncode == 10 and 'round 2, phase 1' in rewritten.stderr)
    events(t / 'events', 'partial', complete=False)
    consumer(65, dict(prenv, REVIEW_TIMEOUT='1'))
    events(t / 'events', original)
    repaired_timeout = consumer(65, dict(prenv, REVIEW_TIMEOUT='60'))
    check('auto-retries-corrected-timeout-setting', True,
          lambda: repaired_timeout.returncode == 10 and 'round 2, phase 1' in repaired_timeout.stderr)
    invalid_env = dict(prenv, REVIEW_TIMEOUT='invalid')
    consumer(66, invalid_env)
    repeated_invalid = consumer(66, invalid_env)
    check('unchanged-preflight-failure-does-not-consume-another-attempt', True,
          lambda: repeated_invalid.returncode == 5
          and len(ledger.read(Path(cmd(SCRIPTS / 'review-round.sh', 'path', mirror, h2, '66',
                                     env=prenv).stdout.strip()))) == 2)
    for number, key in enumerate(['REVIEW_REQUIREMENTS', 'REVIEW_ROUTED', 'REVIEW_CATALOG',
                                  'REVIEW_SUITE_STATUS', 'REVIEW_TOOL_NOTES', 'REVIEW_CODEX_MODEL'], 50):
        consumer(number)
        changed = consumer(number, dict(prenv, **{key: 'changed caller input'}))
        check('cache-invalidates-' + key.lower(), True,
              lambda: 'round 2, phase 2' in changed.stderr and changed.returncode == 10)
    consumer(56)
    (lessons / 'measured/LEAD.md').write_text('A changed host-selected question.\n')
    changed = consumer(56)
    check('cache-invalidates-lesson-bytes', True, lambda: 'round 2, phase 2' in changed.stderr)
    response = t / 'cache-response.md'
    response.write_text('An implementer response.')
    response_env = dict(prenv, REVIEW_RESPONSE=str(response))
    consumer(57)
    consumer(57, response_env, phase='2')
    removed = consumer(57)
    check('cache-invalidates-removed-response', True,
          lambda: 'round 3, phase 2' in removed.stderr and removed.returncode == 11)
    # A failed attempt is visible, not a fresh result or an unbounded automatic retry.
    events(t / 'events', 'partial', complete=False)
    consumer(58)
    failed_cache = consumer(58)
    check('unchanged-failed-auto-does-not-retry', True,
          lambda: failed_cache.returncode == 5 and 'round 2, phase' not in failed_cache.stderr)
    events(t / 'events', original)
    repaired_inputs = consumer(58, dict(prenv, REVIEW_TOOL_NOTES='transport repaired'))
    check('changed-inputs-can-retry-failed-execution', True,
          lambda: repaired_inputs.returncode == 10 and 'round 2, phase 1' in repaired_inputs.stderr)
    unseen_artifacts = t / 'status-only'
    status = consumer(59, dict(prenv, REVIEW_ARTIFACTS=str(unseen_artifacts)), phase='status')
    check('status-is-readonly-without-history', True,
          lambda: status.returncode == 0 and 'NOT_REVIEWED' in status.stdout and not unseen_artifacts.exists())
    bad_executor = cmd(SCRIPTS / 'review-round.sh', '1', repo, h1, 'invalid-executor', base,
                       'not-an-executor', env=env)
    check('invalid-executor-was-not-executed', True,
          lambda: bad_executor.returncode == 5
          and ledger.read(root_for('invalid-executor'))[-1]['executed'] is False)
    fresh_status = consumer(58, dict(prenv, REVIEW_TOOL_NOTES='transport repaired'), phase='status')
    stale_status = consumer(58, phase='status')
    check('status-distinguishes-fresh-and-stale-inputs', True,
          lambda: 'RECORDED FRESH' in fresh_status.stdout and 'RECORDED STALE' in stale_status.stdout)
    # The target tip can move without changing merge-base or head.
    consumer(60)
    other_target = git(repo, 'commit-tree', base + '^{tree}', '-p', base, '-m', 'divergent target')
    metadata.write_text(json.dumps({'number': 60, 'headRefOid': h2, 'baseRefOid': other_target}))
    target_move = cmd(SCRIPTS / 'review-pr.sh', repo, '60', 'auto', 'stub', env=prenv)
    check('cache-invalidates-target-tip-with-same-merge-base', True,
          lambda: target_move.returncode == 10 and 'round 2, phase 2' in target_move.stderr)
    changed_install = t / 'changed-install'
    shutil.copytree(SCRIPTS.parent, changed_install, ignore=shutil.ignore_patterns('__pycache__'))
    consumer(61)
    with (changed_install / 'scripts/lib/events.py').open('a') as f:
        f.write('\n# host-selected protocol update\n')
    protocol_move = cmd(changed_install / 'scripts/review-pr.sh', repo, '61', 'auto', 'stub', env=prenv)
    check('cache-invalidates-protocol-install', True,
          lambda: protocol_move.returncode == 10 and 'round 2, phase 2' in protocol_move.stderr)
    # Real child processes exercise cancellation, timeout, lock visibility and final HEAD
    # freshness. This fake CLI emits fixture events; it never invokes a model.
    fake_codex = fakebin / 'codex'
    fake_codex.write_text('#!' + sys.executable + '\n' + '''
import json, os, subprocess, sys, time
from pathlib import Path
mode = os.environ.get('TEST_EXECUTOR_MODE', '')
if mode == 'wait':
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    Path(os.environ['TEST_READY']).write_text(json.dumps([os.getpid(), child.pid, os.getcwd()]))
    time.sleep(60)
elif mode == 'head':
    subprocess.run(['git', '-C', os.environ['TEST_REPO'], 'update-ref',
                    'refs/heads/moving', os.environ['TEST_NEXT_HEAD']], check=True)
elif mode in ('pr', 'gh-error'):
    path = Path(os.environ['TEST_PR_METADATA'])
    data = json.loads(path.read_text())
    data['headRefOid'] = os.environ['TEST_NEXT_HEAD']
    path.write_text('invalid metadata' if mode == 'gh-error' else json.dumps(data))
elif mode == 'protocol':
    path = Path(os.environ['TEST_SKILL'])
    path.write_bytes(path.read_bytes() + b'\\nUpdated during the review.\\n')
sys.stdout.write(Path(os.environ['TEST_EVENTS']).read_text())
''')
    fake_codex.chmod(0o755)
    liveenv = dict(prenv, TEST_EVENTS=str(t / 'events'), TEST_REPO=str(repo), TEST_NEXT_HEAD=special)
    events(t / 'events', original)
    git(repo, 'branch', 'moving', h1)
    moved = cmd(SCRIPTS / 'review-round.sh', '1', repo, 'moving', 'moving-head', base, 'codex',
                env=dict(liveenv, TEST_EXECUTOR_MODE='head'))
    moved_rows = ledger.read(root_for('moving-head'))
    check('completion-rechecks-mutable-local-head', True,
          lambda: moved.returncode == 5 and 'STALE' in moved.stdout
          and moved_rows[-1]['recorded'] and not moved_rows[-1]['fresh_at_finish'])
    moved_report = host('report', pr='moving-head')
    check('report-preserves-finish-staleness-and-reason', True,
          lambda: 'freshness at finish: STALE' in moved_report.stdout
          and 'requested head changed during review' in moved_report.stdout)
    for number, mode in [(62, 'pr'), (63, 'gh-error')]:
        result = consumer(number, dict(liveenv, TEST_EXECUTOR_MODE=mode), executor='codex')
        check('completion-rechecks-remote-' + mode, True,
              lambda: result.returncode == 5 and 'RECORDED STALE' in result.stdout)
    starting_protocol = protocol.protocol_sha256(changed_install / 'scripts')
    upgraded = cmd(changed_install / 'scripts/review-round.sh', '1', repo, h1, 'live-upgrade', base, 'codex',
                   env=dict(liveenv, TEST_EXECUTOR_MODE='protocol', TEST_SKILL=str(changed_install / 'SKILL.md')))
    upgrade_root = root_for('live-upgrade')
    upgrade_rows = ledger.read(upgrade_root)
    check('mid-round-upgrade-preserves-start-version-and-records-staleness', True,
          lambda: upgraded.returncode == 5 and upgrade_rows[-1]['recorded']
          and upgrade_rows[-1]['fresh_at_finish'] is False
          and upgrade_rows[0]['skill_sha256'] == starting_protocol
          and starting_protocol != protocol.protocol_sha256(changed_install / 'scripts')
          and 'protocol_sha256: ' + starting_protocol in (upgrade_root / 'round-0001/SEAL.txt').read_text())
    ready = t / 'executor-ready.json'
    def wait_ready(process):
        until = time.monotonic() + 20
        while time.monotonic() < until and process.poll() is None and not ready.exists():
            time.sleep(0.02)
        require(ready.exists(), 'test-ready', 'fake executor did not start')
        return json.loads(ready.read_text())
    def stopped(pid):
        state = cmd('ps', '-o', 'stat=', '-p', str(pid)).stdout.strip()
        return not state or state.startswith('Z')
    for label, timeout, sig in [('timeout', '1', None), ('sigterm', '60', signal.SIGTERM),
                                 ('sigint', '60', signal.SIGINT)]:
        ready.unlink(missing_ok=True)
        runenv = dict(liveenv, TEST_EXECUTOR_MODE='wait', TEST_READY=str(ready), REVIEW_TIMEOUT=timeout)
        proc = subprocess.Popen([str(SCRIPTS / 'review-round.sh'), '1', str(repo), h1,
                                 label, base, 'codex'], env=runenv,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            parent_pid, child_pid, checkout = wait_ready(proc)
            if sig:
                status = cmd(SCRIPTS / 'review-round.sh', 'status', repo, h1, label, base, 'codex', env=runenv)
                duplicate = cmd(SCRIPTS / 'review-round.sh', 'auto', repo, h1, label, base, 'codex', env=runenv)
                check(label + '-running-status-and-no-concurrent-execution', True,
                      lambda: status.returncode == 0 and 'RUNNING' in status.stdout
                      and '[concurrent-round]' in duplicate.stderr)
                proc.send_signal(sig)
            stdout, stderr = proc.communicate(timeout=20)
            rows = ledger.read(root_for(label))
            check(label + '-records-one-failure-and-cleans-children', True,
                  lambda: proc.returncode == 5 and len(rows) == 2 and rows[-1]['executed']
                  and not rows[-1]['recorded'] and stopped(parent_pid) and stopped(child_pid)
                  and not Path(checkout).exists())
            after_status = cmd(SCRIPTS / 'review-round.sh', 'status', repo, h1, label, base, 'codex', env=runenv)
            check(label + '-leftover-lock-does-not-claim-running', True,
                  lambda: after_status.returncode == 0 and 'FAILED' in after_status.stdout
                  and 'RUNNING' not in after_status.stdout and (root_for(label) / '.lock').exists())
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
    # A failed spawn and a missing harness check both close the attempt exactly once.
    spec = importlib.util.spec_from_file_location('test_runner', SCRIPTS / 'lib/run-review.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    # Branding must not buy another three attempts by silently selecting a new history root.
    migration_home = (t / 'migration-home').resolve()
    migration_home.mkdir()
    migration_env = {k: v for k, v in env.items() if k != 'REVIEW_ARTIFACTS'}
    with patch.dict(os.environ, migration_env, clear=True), patch.object(Path, 'home', return_value=migration_home):
        fresh_root = runner.root_for(repo, '17')
        check('new-install-uses-frontier-history-root', True,
              lambda: fresh_root.parent.parent == migration_home / '.frontier-simplify-review')
        legacy_root = migration_home / '.sol-simplify-review'
        legacy_root.mkdir()
        retained_root = legacy_root / fresh_root.parent.name / '17'
        shutil.copytree(root, retained_root)
        history_bytes = (retained_root / 'ledger.jsonl').read_bytes()
        check('rename-reuses-legacy-history-root', True, lambda: runner.root_for(repo, '17') == retained_root)
        result = runner.main(['auto', str(repo), h2, '17', base, 'stub'])
        check('rename-preserves-exhausted-budget-and-receipt-bytes', True,
              lambda: result == 11 and (retained_root / 'ledger.jsonl').read_bytes() == history_bytes
              and not (fresh_root / 'round-0001').exists())
        fresh_root.parent.parent.mkdir(exist_ok=True)
        check('legacy-history-still-wins-if-new-root-also-exists', True,
              lambda: runner.root_for(repo, '17') == retained_root)
    real_popen = subprocess.Popen
    def missing_cli(command, *args, **kwargs):
        if command[0] == 'codex':
            raise FileNotFoundError('test: executor binary missing')
        return real_popen(command, *args, **kwargs)
    with patch.dict(os.environ, env, clear=True), patch.object(subprocess, 'Popen', missing_cli):
        result = runner.main(['1', str(repo), h1, 'missing-cli', base, 'codex'])
    check('spawn-failure-is-not-executed', True,
          lambda: result == 5 and not ledger.read(root_for('missing-cli'))[-1]['executed'])
    real_guard = ledger.shell_guard
    def missing_check(name, *args):
        if name == 'guard_turn_completed':
            raise ledger.MissingGuard('test: completion check missing')
        return real_guard(name, *args)
    with patch.dict(os.environ, env, clear=True), patch.object(ledger, 'shell_guard', missing_check):
        result = runner.main(['1', str(repo), h1, 'missing-check', base, 'stub'])
    rows = ledger.read(root_for('missing-check'))
    check('harness-exception-closes-attempt-once', True,
          lambda: result == 5 and len(rows) == 2 and rows[-1]['executed'] and not rows[-1]['recorded'])
    (t / 'events').write_text('{"type":"result","subtype":"error_during_execution","is_error":true}\n')
    check('executor-error-result-rejected', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'completed', t / 'events').returncode != 0)
    (t / 'events').write_text(json.dumps({'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"type":"command_execution"}'}}) + '\n')
    check('executor-prose-is-not-tool-execution', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'commands', t / 'events').returncode != 0)
    (t / 'events').write_text('{"type":"turn.completed"}\n{"type":"turn.started"}\n')
    check('executor-earlier-turn-not-completion', True,
          lambda: cmd(sys.executable, SCRIPTS / 'lib/events.py', 'completed', t / 'events').returncode != 0)
    # These execute Node itself: an empty selector can report a passing file wrapper on Node 22.
    node_repo = t / 'node-witness'
    node_repo.mkdir()
    probe = node_repo / 'probe.test.mjs'
    preamble = 'import test from "node:test"; import assert from "node:assert/strict";\n'
    def named_case(label, body, name='named witness', timeout=10):
        probe.write_text(preamble + body)
        output = t / label
        output.mkdir()
        return witness.run_named(node_repo, probe.name, name, output, timeout)
    check('named-witness-passes', True,
          lambda: named_case('node-pass', 'test("named witness", () => assert.equal(1,1));') == 'PASS')
    check('named-witness-assertion-fails', True,
          lambda: named_case('node-fail', 'test("named witness", () => assert.equal(1,2));') == 'ASSERTION_FAILED')
    check('named-witness-regexp-punctuation-is-literal', True,
          lambda: named_case('node-literal', 'test("named (a|b).$", () => assert.ok(true));', 'named (a|b).$') == 'PASS')
    check('named-witness-wrapper-pass-is-not-selection', False,
          lambda: named_case('node-empty', 'test("different name", () => assert.fail());'), 'witness-selection')
    check('named-witness-live-alternative-cannot-hide-missing-name', False,
          lambda: named_case('node-alternative', 'test("named witness", () => assert.ok(true));', 'named witness|missing'), 'witness-selection')
    check('named-witness-skip-is-not-execution', False,
          lambda: named_case('node-skip', 'test("named witness", {skip:true}, () => assert.fail());'), 'witness-selection')
    check('named-witness-todo-is-not-execution', False,
          lambda: named_case('node-todo', 'test("named witness", {todo:true}, () => assert.fail());'), 'witness-selection')
    check('named-witness-load-error-is-not-kill', False,
          lambda: named_case('node-load', 'throw new Error("load failure");'), 'witness-selection')
    check('named-witness-runtime-error-is-not-assertion', False,
          lambda: named_case('node-error', 'test("named witness", () => { throw new Error("environment failure"); });'), 'witness-assertion')
    check('named-witness-timeout-is-not-kill', False,
          lambda: named_case('node-timeout', 'test("named witness", async () => { await new Promise(r => setTimeout(r, 10000)); });', timeout=0.1), 'witness-timeout')
    check('named-witness-duplicate-name-is-ambiguous', False,
          lambda: named_case('node-duplicate', 'test("named witness", () => {}); test("named witness", () => {});'), 'witness-selection')
    check('named-witness-late-process-error-is-not-pass', False,
          lambda: named_case('node-late-error', 'test("named witness", () => {}); process.on("exit", () => {process.exitCode=1;});'), 'witness-process')
    # A measured contrast, not a status file, publishes a review lead.
    git(node_repo, 'init', '-q')
    git(node_repo, 'config', 'user.name', 'test')
    git(node_repo, 'config', 'user.email', 'test@example.invalid')
    probe.write_text(preamble + 'import { value } from "./value.mjs"; test("named witness", () => assert.equal(value, 2));')
    (node_repo / 'value.mjs').write_text('export const value = 1;')
    git(node_repo, 'add', probe.name, 'value.mjs')
    git(node_repo, 'commit', '-qm', 'broken behavior')
    broken = git(node_repo, 'rev-parse', 'HEAD')
    (node_repo / 'value.mjs').write_text('export const value = 2;')
    git(node_repo, 'add', 'value.mjs')
    git(node_repo, 'commit', '-qm', 'repair')
    fixed = git(node_repo, 'rev-parse', 'HEAD')
    source = t / 'source-review.md'
    source.write_text('F-1: named witness reproduces the wrong value.')
    replay_args = (node_repo, broken, fixed, probe.name, 'named witness', source, 'Check the independently expected value.')
    check('witness-replay-publishes-observed-contrast', True,
          lambda: 'named assertion failed before and passed after' in witness.replay(*replay_args, t / 'observed'))
    check('witness-replay-reversed-repair-does-not-publish', False,
          lambda: witness.replay(node_repo, fixed, broken, probe.name, 'named witness', source, 'Question', t / 'reversed'), 'witness-contrast')
    check('witness-replay-failure-leaves-no-lead', True, lambda: not (t / 'reversed/LEAD.md').exists())
    check('witness-replay-cannot-reuse-stale-success-directory', False,
          lambda: witness.replay(*replay_args, t / 'observed'))
    check('witness-replay-same-head-is-not-contrast', False,
          lambda: witness.replay(node_repo, fixed, fixed, probe.name, 'named witness', source, 'Question', t / 'same'), 'witness-target')
    check('witness-replay-refuses-consumer-output', False,
          lambda: witness.replay(*replay_args, node_repo / 'output'), 'witness-location')
    check('witness-replay-refuses-escaping-test', False,
          lambda: witness.replay(node_repo, broken, fixed, '../probe.mjs', 'name', source, 'Question', t / 'escape'), 'witness-path')
    check('witness-replay-refuses-empty-lesson', False,
          lambda: witness.replay(node_repo, broken, fixed, probe.name, 'named witness', source, '', t / 'no-lesson'), 'witness-input')
    check('witness-replay-source-checkout-untouched', True,
          lambda: git(node_repo, 'status', '--porcelain') == '' and git(node_repo, 'rev-parse', 'HEAD') == fixed)
    probe.write_text(preamble + 'import { writeFileSync } from "node:fs"; '
                    'test("named witness", () => { writeFileSync(new URL(import.meta.url), "changed"); assert.fail("probe"); });')
    git(node_repo, 'add', probe.name)
    git(node_repo, 'commit', '-qm', 'self-changing witness')
    changing = git(node_repo, 'rev-parse', 'HEAD')
    check('witness-replay-rejects-test-byte-changes', False,
          lambda: witness.replay(node_repo, broken, changing, probe.name, 'named witness', source, 'Question', t / 'changing'), 'witness-bytes')
    # The poller distinguishes an expected handoff from a child execution error.
    poller_source = SCRIPTS.parents[2] / 'dogfood/run.py'
    if poller_source.exists():
        poller = t / 'poller'
        (poller / 'dogfood').mkdir(parents=True)
        shutil.copyfile(poller_source, poller / 'dogfood/run.py')
        poll_runner = poller / 'skills/frontier-simplify-review/scripts/review-pr.sh'
        poll_runner.parent.mkdir(parents=True)
        poll_runner.write_text('#!/bin/sh\nprintf "%s" "$REVIEW_LESSONS" > "$TEST_LESSON_PATH"\nexit "$TEST_CHILD_STATUS"\n')
        poll_runner.chmod(0o755)
        poll_config = poller / 'consumers.json'
        poll_config.write_text(json.dumps({'consumers': [{'repository': str(repo), 'lessons': str(lessons)}]}))
        metadata.write_text('[{"number":42}]')
        poll_env = dict(prenv, REVIEW_CONSUMERS_CONFIG=str(poll_config), TEST_LESSON_PATH=str(poller / 'received'))
        for child, expected in [(10, 0), (11, 0), (5, 1), (0, 1)]:
            check(f'poller-classifies-child-{child}', True,
                  lambda child=child, expected=expected: cmd(sys.executable, poller / 'dogfood/run.py',
                      env=dict(poll_env, TEST_CHILD_STATUS=str(child))).returncode == expected)
        check('poller-delivers-consumer-lessons', True, lambda: (poller / 'received').read_text() == str(lessons))
        poll_runner.write_text('#!/bin/sh\nprintf "%s" "$3" > "$TEST_LESSON_PATH"\nexit 0\n')
        polled_status = cmd(sys.executable, poller / 'dogfood/run.py', '--status', env=poll_env)
        check('poller-status-never-runs-auto', True,
              lambda: polled_status.returncode == 0 and (poller / 'received').read_text() == 'status')
        metadata.write_text('[]')
        idle = cmd(sys.executable, poller / 'dogfood/run.py', env=poll_env)
        check('poller-empty-discovery-is-explicit', True,
              lambda: idle.returncode == 0 and '0 open PRs' in idle.stdout)
        # Exercise the installer without touching launchd or this user's LaunchAgents.
        installer = poller_source.with_name('install.py')
        launch_home = t / 'launch-home'
        legacy_launch = launch_home / 'Library/LaunchAgents/dev.sol-simplify.review-dogfood.plist'
        legacy_launch.parent.mkdir(parents=True)
        legacy_launch.write_bytes(b'legacy poller configuration')
        install_env = dict(env, REVIEW_CONSUMERS_CONFIG=str(poll_config),
                           REVIEW_EXECUTOR='claude', REVIEW_CODEX_MODEL='selected-model', REVIEW_TIMEOUT='90')
        with patch.dict(os.environ, install_env, clear=True), patch.object(Path, 'home', return_value=launch_home), \
                patch.object(sys, 'argv', [str(installer), '--interval', '60', '--artifacts', 'relative-artifacts']), \
                patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as launchctl_calls:
            previous_cwd = Path.cwd()
            try:
                os.chdir(t)
                runpy.run_path(str(installer), run_name='__main__')
            finally:
                os.chdir(previous_cwd)
        launch = plistlib.loads((launch_home / 'Library/LaunchAgents/dev.frontier-simplify.review-dogfood.plist').read_bytes())
        check('installer-disables-legacy-poller-and-preserves-config', True,
              lambda: not legacy_launch.exists()
              and legacy_launch.with_suffix('.plist.disabled').read_bytes() == b'legacy poller configuration'
              and launchctl_calls.call_args_list[0].args[0] == [
                  'launchctl', 'bootout', f'gui/{os.getuid()}/dev.sol-simplify.review-dogfood'])
        check('installer-preserves-selected-config-and-executor', True,
              lambda: all(launch['EnvironmentVariables'].get(k) == install_env[k] for k in
                          ('REVIEW_EXECUTOR', 'REVIEW_CODEX_MODEL', 'REVIEW_TIMEOUT'))
              and Path(launch['EnvironmentVariables']['REVIEW_CONSUMERS_CONFIG']) == poll_config.resolve())
        check('installer-log-paths-are-absolute', True,
              lambda: Path(launch['StandardOutPath']) == (t / 'relative-artifacts/dogfood.log').resolve()
              and Path(launch['StandardErrorPath']) == (t / 'relative-artifacts/dogfood.err').resolve())
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
    candidate = hookrepo / 'skills/frontier-simplify-review/scripts'
    candidate.mkdir(parents=True)
    (candidate / 'selftest.sh').write_text('#!/bin/sh\nexit 0\n')
    (candidate / 'probe.sh').write_text('#!/bin/sh\necho reject\n')
    git(hookrepo, 'add', '.')
    git(hookrepo, 'commit', '-qm', 'seed')
    installed = cmd(SCRIPTS / 'install-hook.sh', hookrepo)
    check('hook-installs', True, lambda: installed.returncode == 0)
    trusted = hookrepo / '.git/hooks/frontier-simplify-review'
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

    old_hook_repo = t / 'legacy-hook-repo'
    old_hook_repo.mkdir()
    git(old_hook_repo, 'init', '-q')
    old_hooks = old_hook_repo / '.git/hooks'
    (old_hooks / 'pre-commit').write_text('#!/bin/sh\n# sol-simplify-review installed hook\nexit 99\n')
    prior_hook = old_hooks / 'pre-commit.before-review'
    prior_hook.write_text('#!/bin/sh\n# existing user hook\nexit 0\n')
    migrated_hook = cmd(SCRIPTS / 'install-hook.sh', old_hook_repo)
    check('hook-rebrand-preserves-original-user-hook-without-chaining-old-driver', True,
          lambda: migrated_hook.returncode == 0 and 'existing user hook' in prior_hook.read_text()
          and 'frontier-simplify-review installed hook' in (old_hooks / 'pre-commit').read_text())

    events(t / 'legacy-seal-event', 'review', tools=False)
    with (t / 'legacy-seal-event').open('a') as f:
        f.write(json.dumps({'type': 'item.completed', 'item': {'type': 'command_execution',
                      'command': 'cat x', 'aggregated_output': 'schema: sol-simplify-review-seal.v1'}}) + '\n')
    check('legacy-seal-evidence-is-still-recognized', False,
          lambda: ledger.shell_guard('guard_seal_unseen', t / 'legacy-seal-event'), 'seal-seen')

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
