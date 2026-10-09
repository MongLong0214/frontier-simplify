#!/usr/bin/env python3
"""Follow-up stops: preserved witnesses, redesign requests and granted supplementary reviews."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'lib'))
import evidence
import followup
import ledger
from protocol import Rejected, child_environment

results = []


def check(name, value):
    print(('ok   ' if value else 'NOT OK ') + name)
    results.append(bool(value))


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def commit(repo, files, message):
    for name, text in files.items():
        (repo / name).write_text(text)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', message)
    return git(repo, 'rev-parse', 'HEAD')


def stub(path, text):
    path.write_text('\n'.join(json.dumps(event) for event in [
        {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'cat a.txt'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': text}},
        {'type': 'turn.completed'}]) + '\n')


OPEN = ('F-1 BLOCKER: a.txt still says bug.\n'
        '- invariant: receipt-delivered | family 5 | OPEN | A receipt completes only when the answer was delivered.\n')

# --- parsers, no repository ----------------------------------------------------------------------
found = followup.invariants(
    '- invariant: `K1` | family 2, 5 | open | sentence | with a pipe\n'
    '* invariant: K2 | 5 | ESCAPE | other\n'
    '- invariant: K3 | family 11 | OPEN | out of range\n'
    '- invariant: K4 | family 5 | MAYBE | unknown status\n'
    '- invariant: bad key! | family 5 | OPEN | rejected key\n'
    'text mentioning invariant: K5 | family 5 | OPEN inline is not a line\n')
check('invariant-lines-parse-families-status-and-sentence',
      found.get('K1') == {'families': [2, 5], 'status': 'OPEN', 'sentence': 'sentence | with a pipe'}
      and found.get('K2', {}).get('status') == 'ROUND1-ESCAPE' and set(found) == {'K1', 'K2'})
check('recurrence-needs-the-same-key-open-in-both-latest-reviews',
      followup.recurring([(1, '- invariant: A | family 5 | OPEN | s\n- invariant: B | family 2 | OPEN | s'),
                          (2, '- invariant: A | family 5 | REGRESSION | s\n- invariant: B | family 2 | CLOSED | s')])
      == ['A'])
check('one-review-cannot-recur', followup.recurring([(1, OPEN)]) == [])
check('a-closed-key-between-two-opens-is-not-consecutive',
      followup.recurring([(1, OPEN), (2, OPEN.replace('OPEN |', 'CLOSED |')), (3, OPEN)]) == [])
check('unreceipted-finding-ids-are-flagged-and-standards-ignored',
      followup.unreceipted('Closed F-1 and ESCAPE-SUPP-15; SHA-256 and UTF-8 unchanged; CVE-2024-1.',
                           ['F-1 BLOCKER at a.txt:1']) == ['ESCAPE-SUPP-15'])
deny_list = (b'diff --git a/src/r.py b/src/r.py\n--- a/src/r.py\n+++ b/src/r.py\n@@ -1 +1,4 @@\n'
             b'+    if text.startswith("No reply"):\n+        return False\n+    # comment\n+    value = 1\n'
             b'diff --git a/tests/test_r.py b/tests/test_r.py\n+++ b/tests/test_r.py\n'
             b'+def test_x():\n+    assert x\n+    assert y\n')
check('repair-shape-counts-code-lines-outside-tests', followup.repair_shape(deny_list) == (3, 2))
rows = followup.tracked([(4, OPEN)])
check('repair-shape-warning-for-open-family-5',
      'receipt-delivered' in (followup.shape_warning(rows, 4, deny_list) or ''))
check('repair-shape-silent-for-other-families',
      followup.shape_warning(followup.tracked([(4, OPEN.replace('family 5', 'family 2'))]), 4, deny_list) is None)
for bad in ('../x.sh', 'review_evidence', '/tmp/review_evidence/x.sh', 'review_evidence/../x.sh', 'other/x.sh'):
    try:
        evidence.evidence_path(bad)
        check(f'witness-path-rejects-{bad}', False)
    except Rejected:
        check(f'witness-path-rejects-{bad}', True)
check('obsolete-needs-a-reason',
      evidence.OBSOLETE.findall('- witness_obsolete: F-1 -- api removed\n- witness_obsolete: F-2\n')
      == [('F-1', 'api removed'), ('F-2', '')])

with tempfile.TemporaryDirectory(prefix='review-followup-test-') as temporary:
    t = Path(temporary).resolve()

    # --- collection: what survives the checkout -----------------------------------------------------
    clone = t / 'clone'
    clone.mkdir()
    git(clone, 'init', '-q')
    (clone / 'review_evidence').mkdir()
    (clone / 'review_evidence' / 'tracked.txt').write_text('tracked\n')
    git(clone, 'add', '.')
    git(clone, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'c')
    (clone / 'review_evidence' / 'F-1.sh').write_text('exit 1\n')
    (clone / 'review_evidence' / 'F-1.sh').chmod(0o755)
    (clone / 'review_evidence' / 'old.sh').write_text('exit 0\n')
    (clone / 'review_evidence' / 'node_modules').mkdir()
    (clone / 'review_evidence' / 'node_modules' / 'dep.js').write_text('x')
    (clone / 'review_evidence' / 'link.sh').symlink_to('/etc/hosts')
    (clone / 'review_evidence' / 'big.bin').write_bytes(b'0' * (evidence.MAX_FILE + 1))
    out = t / 'round'
    out.mkdir()
    from protocol import digest
    check('collect-reports-it-preserved-something',
          evidence.collect(clone, out, {'review_evidence/old.sh': digest(b'exit 0\n')}))
    manifest = json.loads((out / 'WITNESSES.json').read_text())
    kept = [f['path'] for f in manifest['files']]
    skipped = {s['path'] for s in manifest['skipped']}
    check('collect-keeps-new-files-only', kept == ['review_evidence/F-1.sh']
          and (out / 'witnesses/review_evidence/F-1.sh').read_text() == 'exit 1\n')
    check('collect-keeps-the-executable-bit',
          (out / 'witnesses/review_evidence/F-1.sh').stat().st_mode & 0o111 != 0)
    check('collect-skips-links-dependencies-and-oversize',
          {'review_evidence/link.sh', 'review_evidence/node_modules/', 'review_evidence/big.bin'} <= skipped)
    check('collect-ignores-tracked-and-unchanged-installed',
          'review_evidence/tracked.txt' not in kept + list(skipped) and 'review_evidence/old.sh' not in kept)
    (t / 'slow').mkdir()
    (t / 'slow' / 'w.sh').write_text('sleep 30\n')
    check('witness-timeout-is-not-a-pass',
          evidence.execute(t / 'slow', 'w.sh', t / 'slow-logs', 0.5)[0] == 'TIMEOUT')
    (t / 'env').mkdir()
    (t / 'env' / 'w.sh').write_text('test -z "${SECRET_TOKEN:-}" && test -n "$PATH"\n')
    with patch.dict(os.environ, SECRET_TOKEN='do-not-leak'):
        check('witnesses-do-not-inherit-host-secrets',
              evidence.execute(t / 'env', 'w.sh', t / 'env-logs', 30)[0] == 'PASS')
    wrapper = t / 'wrapper.sh'
    wrapper.write_text(f'#!/bin/sh\ntouch {t}/wrapped\nexec "$@"\n')
    wrapper.chmod(0o755)
    check('the-wrapper-runs-each-witness',
          evidence.execute(t / 'env', 'w.sh', t / 'wrapped-logs', 30, [str(wrapper)])[0] == 'PASS'
          and (t / 'wrapped').exists())
    real_wait = subprocess.Popen.wait
    def cancelled_wait(self, timeout=None):
        if timeout is not None:
            raise InterruptedError('witness precheck interrupted by SIGTERM')
        return real_wait(self, timeout=timeout)
    try:
        with patch.object(subprocess.Popen, 'wait', cancelled_wait):
            evidence.execute(t / 'slow', 'w.sh', t / 'cancel-logs', 30)
        check('cancellation-stops-the-precheck', False)
    except InterruptedError:
        check('cancellation-stops-the-precheck', True)

    # --- a consumer repository and a stub reviewer --------------------------------------------------
    repo = t / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    base = commit(repo, {'a.txt': 'ok\n', 'b.txt': 'b0\n'}, 'base')
    h1 = commit(repo, {'a.txt': 'bug\n'}, 'change')
    h2 = commit(repo, {'b.txt': 'b1\n'}, 'unrelated repair')
    h3 = commit(repo, {'a.txt': 'fixed\n'}, 'real repair')
    h4 = commit(repo, {'b.txt': 'b2\n'}, 'later')
    witness_dir = t / 'reviewer-evidence'
    witness_dir.mkdir()
    (witness_dir / 'F-1.sh').write_text('. review_evidence/lib.sh\n! has_bug\n')
    (witness_dir / 'lib.sh').write_text('has_bug() { grep -q bug a.txt; }\n')
    events = t / 'events.jsonl'
    env = {k: v for k, v in child_environment().items() if not k.startswith('REVIEW_')}
    env.update(REVIEW_ARTIFACTS=str(t / 'artifacts'), REVIEW_STUB=str(events), PYTHONDONTWRITEBYTECODE='1')

    def host(phase, head, pr, *extra, **more):
        return subprocess.run([str(SCRIPTS / 'review-round.sh'), phase, str(repo), head, pr, base, 'stub', *extra],
                              env=dict(env, **more), capture_output=True, text=True)

    def root(pr):
        return Path(host('path', h1, pr).stdout.strip())

    # --- witnesses: preserved, rerun first, and a failure uses no attempt ---------------------------
    stub(events, OPEN.replace('invariant: receipt-delivered', 'invariant: w-key'))
    first = host('1', h1, 'w', REVIEW_STUB_EVIDENCE=str(witness_dir))
    w = root('w')
    check('round-1-preserves-reviewer-witnesses', first.returncode == 10
          and (w / 'round-0001/witnesses/review_evidence/F-1.sh').is_file()
          and 'WITNESSES.json' in ledger.read(w)[-1]['outputs'])
    unfinished = host('2', h2, 'w')
    check('failing-witness-returns-13-without-an-attempt',
          unfinished.returncode == 13 and len(ledger.audit(w, repo)[0]) == 1
          and '| F-1 | 1 | FAIL |' in unfinished.stdout and 'WITNESS_FAILING F-1' in unfinished.stderr)
    preflight = host('witnesses', h2, 'w')
    check('witness-preflight-is-the-same-check', preflight.returncode == 13 and '| F-1 | 1 | FAIL |' in preflight.stdout)
    check('witness-preflight-passes-on-the-repair', host('witnesses', h3, 'w').returncode == 0)
    stub(events, 'F-1 CLOSED: the witness passes and a.txt no longer says bug.\n'
                 '- invariant: w-key | family 5 | CLOSED | s\n')
    repaired = host('2', h3, 'w', REVIEW_STUB_EVIDENCE=str(witness_dir))
    results_text = (w / 'round-0002/WITNESS_RESULTS.md').read_text() if repaired.returncode == 10 else ''
    check('passing-witnesses-reach-the-reviewer-as-an-input',
          repaired.returncode == 10 and '| F-1 | 1 | PASS |' in results_text
          and 'WITNESS_RESULTS.md' in ledger.audit(w, repo)[0][2]['inputs'])
    check('unchanged-restored-witnesses-are-not-preserved-twice',
          'WITNESSES.json' not in ledger.read(w)[-1]['outputs'])
    stub(events, 'F-1 CLOSED.\n- witness_obsolete: F-1 -- the repair removed the path it drives\n')
    retired = host('2', h4, 'w')
    check('obsolete-witness-is-recorded-with-its-reason',
          retired.returncode == 11 and 'retired in attempt 3: the repair removed the path it drives'
          in host('report', h4, 'w').stdout)
    check('retired-witness-is-not-rerun', host('witnesses', h2, 'w').returncode == 0)

    stub(events, OPEN)
    host('1', h1, 'adopted', REVIEW_STUB_EVIDENCE=str(witness_dir))
    git(repo, 'switch', '-q', '-c', 'adopt', h2)
    (repo / 'review_evidence').mkdir()
    adopted_head = commit(repo, {'review_evidence/F-1.sh': 'exit 0\n'}, 'witness rewritten by the repair')
    git(repo, 'switch', '-q', '-')
    adopted = host('2', adopted_head, 'adopted')
    check('a-tree-cannot-replace-the-witness-it-is-judged-by',
          adopted.returncode == 13 and '| F-1 | 1 | FAIL |' in adopted.stdout
          and "the preserved copy replaced the tree's file" in adopted.stdout)
    git(repo, 'switch', '-q', '--detach', h2)
    (repo / 'review_evidence').mkdir(exist_ok=True)
    shadow_head = commit(repo, {'review_evidence/lib.sh': 'has_bug() { return 1; }\n'}, 'helper rewritten')
    git(repo, 'switch', '-q', '-')
    host('1', h1, 'shadow', REVIEW_STUB_EVIDENCE=str(witness_dir))
    shadowed = host('2', shadow_head, 'shadow')
    check('a-tree-cannot-replace-a-helper-its-witness-reads',
          shadowed.returncode == 13 and '| F-1 | 1 | FAIL |' in shadowed.stdout
          and len(ledger.read(root('shadow'))) == 3)

    outside = t / 'outside'
    outside.mkdir()
    linked_evidence = t / 'linked-evidence'
    (linked_evidence / 'sub').mkdir(parents=True)
    (linked_evidence / 'F-1.sh').write_text('! grep -q bug a.txt\n')
    (linked_evidence / 'sub' / 'x.txt').write_text('helper\n')
    host('1', h1, 'link', REVIEW_STUB_EVIDENCE=str(linked_evidence))
    git(repo, 'switch', '-q', '--detach', h3)
    (repo / 'review_evidence').mkdir(exist_ok=True)
    (repo / 'review_evidence' / 'sub').symlink_to(outside)
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'evidence link')
    link_head = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'switch', '-q', '-')
    linked = host('2', link_head, 'link')
    check('restoration-never-writes-through-a-link',
          linked.returncode == 10 and not any(outside.iterdir())
          and '| F-1 | 1 | PASS |' in (root('link') / 'round-0002/WITNESS_RESULTS.md').read_text())

    host('1', h1, 'restart', REVIEW_STUB_EVIDENCE=str(witness_dir))
    restarted = host('1', h2, 'restart')
    check('a-phase-1-restart-still-reruns-witnesses',
          restarted.returncode == 13 and len(ledger.read(root('restart'))) == 3
          and host('witnesses', h2, 'restart').returncode == 13)
    rerun = host('1', h3, 'restart')
    restart_round = root('restart') / 'round-0002'
    check('a-restarted-scope-review-carries-witnesses-and-redesign',
          rerun.returncode == 10 and '| F-1 | 1 | PASS |' in (restart_round / 'WITNESS_RESULTS.md').read_text()
          and (restart_round / 'IMPLEMENTER_REDESIGN.md').is_file()
          and not (restart_round / 'REMEDIATION.patch').exists()
          and 'restarted scope review' in (restart_round / 'prompt.txt').read_text())

    host('1', h1, 'disputed', REVIEW_STUB_EVIDENCE=str(witness_dir))
    disputed = host('2', h2, 'disputed', REVIEW_WITNESS_DISPUTED='F-1',
                    REVIEW_WITNESS_WRAPPER=f'{wrapper} --')
    check('disputed-witness-lets-the-reviewer-judge',
          disputed.returncode == 10 and 'failing, disputed by the implementer'
          in (root('disputed') / 'round-0002/WITNESS_RESULTS.md').read_text())

    # --- redesign: the same open key twice stops the next review ------------------------------------
    response = t / 'response.md'
    response.write_text('Removed the No reply path for ESCAPE-SUPP-15 and F-1.\n')
    stub(events, OPEN)
    host('1', h1, 'r')
    second = host('2', h2, 'r', REVIEW_RESPONSE=str(response))
    r = root('r')
    prompt = (r / 'round-0002/prompt.txt').read_text()
    check('carried-invariant-and-unreceipted-id-reach-the-prompt',
          second.returncode == 10 and 'receipt-delivered | family 5 | OPEN in attempt 1' in prompt
          and 'ESCAPE-SUPP-15' in prompt and 'ESCAPE-SUPP-15' in second.stderr)
    stopped = host('2', h3, 'r')
    request = r / 'REDESIGN-REQUIRED.md'
    check('recurring-key-returns-12-without-an-attempt',
          stopped.returncode == 12 and len(ledger.audit(r, repo)[0]) == 2
          and 'REDESIGN_REQUIRED receipt-delivered' in stopped.stderr)
    check('redesign-request-renders-the-skill-template',
          request.is_file() and 'receipt-delivered open in attempts 1, 2' in request.read_text()
          and '## Single enforcement point' in request.read_text())
    check('status-names-the-required-redesign',
          'REDESIGN_REQUIRED before another review: receipt-delivered' in host('status', h3, 'r').stdout)
    check('a-phase-1-restart-cannot-skip-the-redesign',
          host('1', h3, 'r').returncode == 12 and len(ledger.audit(r, repo)[0]) == 2)
    moved_base = subprocess.run([str(SCRIPTS / 'review-round.sh'), 'auto', str(repo), h3, 'r', h1, 'stub'],
                                env=env, capture_output=True, text=True)
    check('a-changed-base-cannot-skip-the-redesign',
          moved_base.returncode == 12 and len(ledger.audit(r, repo)[0]) == 2)
    design = t / 'redesign.md'
    design.write_text('# Redesign\nOne certification point records provenance at the producer.\n')
    third = host('2', h3, 'r', REVIEW_REDESIGN=str(design))
    check('supplied-redesign-is-frozen-for-the-reviewer',
          third.returncode == 11 and (r / 'round-0003/IMPLEMENTER_REDESIGN.md').read_bytes() == design.read_bytes()
          and ledger.read(r)[-3]['redesign_supplied'] is True)
    check('the-automatic-limit-writes-a-decision-document',
          (r / 'HANDOFF.md').is_file() and '## Decision requested' in (r / 'HANDOFF.md').read_text()
          and '| receipt-delivered | 5 | OPEN | 3 | 1, 2, 3 |' in (r / 'HANDOFF.md').read_text())
    grant = ['--supplementary', '--granted-by', 'maintainer', '--budget', '2']
    again = host('2', h4, 'r', *grant, REVIEW_REDESIGN=str(design))
    check('an-already-reviewed-redesign-does-not-reopen-review',
          again.returncode == 12 and 'already reviewed' in again.stderr and len(ledger.audit(r, repo)[0]) == 3)
    design.write_text('# Redesign\nA second design: one allow-list at the sink.\n')
    stub(events, OPEN.replace('| OPEN |', '| CLOSED |'))
    fourth = host('2', h4, 'r', *grant, REVIEW_REDESIGN=str(design))
    started = ledger.read(r)[-3]
    check('a-new-redesign-runs-under-the-grant',
          fourth.returncode == 10 and started.get('supplementary') ==
          {'granted_by': 'maintainer', 'budget': 2, 'number': 1}
          and 'supplementary review 1 of 2 granted by maintainer' in (r / 'round-0004/prompt.txt').read_text())

    # --- supplementary budget -----------------------------------------------------------------------
    stub(events, 'F-1 BLOCKER: a.txt still says bug.\n')
    early = host('1', h1, 's', *grant)
    check('a-grant-cannot-replace-remaining-automatic-attempts',
          early.returncode == 5 and '[supplementary]' in early.stderr and not ledger.read(root('s')))
    for head in (h1, h2, h3):
        last = host('auto', head, 's')
    s = root('s')
    check('third-automatic-attempt-hands-off', last.returncode == 11 and (s / 'HANDOFF.md').is_file())
    check('no-grant-no-review', host('2', h4, 's').returncode == 11 and len(ledger.read(s)) == 9)
    check('a-grant-needs-a-granter-and-budget',
          host('2', h4, 's', '--supplementary').returncode == 2
          and host('2', h4, 's', '--budget', '1').returncode == 2
          and host('2', h4, 's', '--supplementary', '--granted-by', 'x', '--budget', '0').returncode == 2)
    one = ['--supplementary', '--granted-by', 'maintainer', '--budget', '1']
    supplementary = host('2', h4, 's', *one)
    check('every-round-starts-with-the-cumulative-count',
          supplementary.stderr.splitlines()[0].startswith(
              'review: PR cumulative reviews 3 (automatic 3/3, supplementary 0/1 granted by maintainer), '
              'cumulative time '))
    handoff = (s / 'HANDOFF.md').read_text()
    check('spent-grant-hands-off-with-a-decision-request',
          supplementary.returncode == 11 and 'supplementary budget of 1 granted by maintainer is spent' in handoff
          and 'Shrink the contract' in handoff and 'Accept the risk and merge' in handoff
          and 'PR cumulative reviews 4 (automatic 3/3, supplementary 1/1 granted by maintainer)' in handoff)
    spent = host('2', h4, 's', *one)
    check('a-spent-grant-launches-nothing', spent.returncode == 11 and len(ledger.audit(s, repo)[0]) == 4)
    check('report-shows-the-cumulative-line',
          'supplementary 1/1 granted by maintainer' in host('report', h4, 's').stdout)
    automatic, used, recorded_grant = ledger.budget(ledger.audit(s, repo)[0])
    check('budget-counts-automatic-and-supplementary-apart',
          (automatic, used, recorded_grant['granted_by']) == (3, 1, 'maintainer'))

    # --- the PR adapter: the budget line comes first there too ---------------------------------------
    git(repo, 'remote', 'add', 'origin', str(repo))
    fake = t / 'bin'
    fake.mkdir()
    (fake / 'gh').write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(
        {'number': 9, 'headRefOid': h1, 'baseRefOid': base, 'url': 'offline'})) + ')\n')
    (fake / 'gh').chmod(0o755)
    stub(events, OPEN)
    adapter = subprocess.run([str(SCRIPTS / 'review-pr.sh'), str(repo), '9', 'auto', 'stub'],
                             env=dict(env, PATH=f"{fake}{os.pathsep}{env['PATH']}"),
                             capture_output=True, text=True)
    lines = adapter.stderr.splitlines()
    check('the-pr-adapter-prints-the-cumulative-line-first',
          adapter.returncode == 10 and lines[0].startswith('review: PR cumulative reviews 0 ')
          and any(line.startswith('review-pr: consumer host') for line in lines[1:]))

print(f'followup-selftest: {sum(results)} passed, {len(results) - sum(results)} failed')
sys.exit(0 if all(results) else 1)
