#!/usr/bin/env python3
"""Durable review reservation and host return-code regressions."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import redirect_stderr
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'lib'))
import ledger
from protocol import Rejected


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def check(name, value):
    print(('ok   ' if value else 'NOT OK ') + name)
    return value


with tempfile.TemporaryDirectory(prefix='review-ledger-test-') as temporary:
    t = Path(temporary)
    repo = t / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    (repo / 'a.txt').write_text('before\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'a.txt').write_text('after\n')
    git(repo, 'commit', '-qam', 'head')
    head = git(repo, 'rev-parse', 'HEAD')
    fixture = t / 'events.jsonl'
    fixture.write_text('\n'.join(json.dumps(event) for event in [
        {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'cat a.txt'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message',
         'text': '# Round 1 review inventory\nReviewed a.txt'}},
        {'type': 'turn.completed'}]) + '\n')
    env = {key: value for key, value in os.environ.items() if not key.startswith('REVIEW_')}
    env.update(REVIEW_ARTIFACTS=str(t / 'artifacts'), REVIEW_STUB=str(fixture),
               PYTHONDONTWRITEBYTECODE='1')
    def host(pr, phase='1', h=head, b=base, executor='stub', environment=env):
        return subprocess.run([str(SCRIPTS / 'review-round.sh'), phase, str(repo), h, pr, b, executor],
                              env=environment, capture_output=True, text=True)
    def root(pr):
        return Path(host(pr, phase='path').stdout.strip())
    results = []
    valid = host('valid')
    rows = ledger.read(root('valid'))
    starts, ends, _ = ledger.audit(root('valid'), repo)
    results.append(check('started-prepared-finished-with-effective-inputs',
                         valid.returncode == 10 and [row['event'] for row in rows] ==
                         ['started', 'prepared', 'finished'] and rows[0]['inputs'] == {}
                         and rows[1]['inputs'] == starts[1]['inputs'] and bool(starts[1]['inputs'])
                         and ends[1]['recorded']))
    for mode in ('prose-review-v2', None):
        old = t / ('v2' if mode else 'v1')
        shutil.copytree(root('valid'), old)
        previous = ledger.read(old)
        previous[0]['inputs'] = previous[1]['inputs']
        previous.pop(1)
        previous[0].pop('scope_schema_version', None)
        previous[0]['inputs'].pop('SCOPE.json', None)
        if mode is None:
            previous[0].pop('mode')
            previous[-1]['accepted'] = previous[-1].pop('recorded')
        else:
            previous[0]['mode'] = mode
        (old / 'ledger.jsonl').unlink()
        for event in previous:
            ledger.append(old, event)
        historical_bytes = (old / 'ledger.jsonl').read_bytes()
        old_starts, old_ends, old_originals = ledger.audit(old, repo)
        results.append(check(('v2' if mode else 'v1') + '-history-remains-readable',
                             bool(old_starts) and bool(old_ends) and bool(old_originals)
                             and (old / 'ledger.jsonl').read_bytes() == historical_bytes))
    for name, h, b, executor, environment in [
        ('missing-ref', 'missing-ref', base, 'stub', env),
        ('bad-base', head, 'missing-ref', 'stub', env),
        ('bad-executor', head, base, 'unsupported', env),
        ('bad-timeout', head, base, 'stub', dict(env, REVIEW_TIMEOUT='nan'))]:
        result = host(name, h=h, b=b, executor=executor, environment=environment)
        results.append(check(name + '-returns-five-without-reservation',
                             result.returncode == 5 and not (root(name) / 'ledger.jsonl').exists()
                             and not (root(name) / 'round-0001').exists()))
    help_result = subprocess.run([str(SCRIPTS / 'review-round.sh'), '--help'],
                                 env=env, capture_output=True)
    syntax_result = subprocess.run([str(SCRIPTS / 'review-round.sh'), 'wrong'],
                                   env=env, capture_output=True)
    results.append(check('help-zero-and-syntax-two', help_result.returncode == 0
                         and syntax_result.returncode == 2))
    orphan = root('orphan')
    (orphan / 'round-0001').mkdir(parents=True)
    orphan_run = host('orphan')
    results.append(check('old-unledgered-directory-refused-without-write',
                         orphan_run.returncode == 5 and 'orphan' in orphan_run.stderr.lower()
                         and not (orphan / 'ledger.jsonl').exists()))
    interrupted = root('interrupted')
    interrupted.mkdir(parents=True)
    ledger.append(interrupted, {'event': 'started', 'round': 1, 'mode': ledger.MODE,
                                'phase': 1, 'repo': str(repo), 'pr': 'interrupted',
                                'base_sha': base, 'head_sha': head, 'inputs': {}})
    readable = ledger.audit(interrupted, repo)[0]
    retry = host('interrupted')
    results.append(check('interrupted-reservation-readable-and-next-round-usable',
                         len(readable) == 1 and not (interrupted / 'round-0001').exists()
                         and retry.returncode == 10
                         and [row['event'] for row in ledger.read(interrupted)] ==
                         ['started', 'started', 'prepared', 'finished']))
    pause_script = '''
import importlib.util, os, sys, time
from pathlib import Path
scripts = Path(sys.argv[1])
sys.path.insert(0, str(scripts / 'lib'))
import ledger
spec = importlib.util.spec_from_file_location('runner', scripts / 'lib/run-review.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
original = ledger.append
def held(root, event):
    if event['event'] == os.environ['TEST_PAUSE_EVENT'] and os.environ['TEST_PAUSE_WHEN'] == 'before':
        Path(os.environ['TEST_READY']).write_text('ready')
        time.sleep(60)
    result = original(root, event)
    if event['event'] == os.environ['TEST_PAUSE_EVENT'] and os.environ['TEST_PAUSE_WHEN'] == 'after':
        Path(os.environ['TEST_READY']).write_text('ready')
        time.sleep(60)
    return result
ledger.append = held
sys.exit(runner.main(sys.argv[2:]))
'''
    for label, event, when, expected in [
        ('kill-before-start', 'started', 'before', []),
        ('kill-after-start', 'started', 'after', ['started']),
        ('kill-after-prepared', 'prepared', 'after', ['started', 'prepared'])]:
        ready = t / (label + '.ready')
        kill_env = dict(env, TEST_PAUSE_EVENT=event, TEST_PAUSE_WHEN=when,
                        TEST_READY=str(ready))
        proc = subprocess.Popen([sys.executable, '-B', '-c', pause_script, str(SCRIPTS),
                                 '1', str(repo), head, label, base, 'stub'],
                                env=kill_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            until = time.monotonic() + 10
            while not ready.exists() and proc.poll() is None and time.monotonic() < until:
                time.sleep(0.02)
            reached = ready.exists()
            if reached:
                proc.kill()
            proc.communicate(timeout=10)
            killed_root = root(label)
            raw = ledger.read(killed_root)
            readable = ledger.audit(killed_root, repo)[0]
            retry = host(label)
            results.append(check(label + '-is-readable-and-retry-uses-next-reservation',
                                 reached and proc.returncode == -9
                                 and [row['event'] for row in raw] == expected
                                 and len(readable) == len(expected) - (1 if 'prepared' in expected else 0)
                                 and retry.returncode == 10
                                 and len(ledger.audit(killed_root, repo)[0]) ==
                                 (2 if expected else 1)))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
    over = root('legacy-over-budget')
    over.mkdir(parents=True)
    for number in range(1, 14):
        ledger.append(over, {'event': 'started', 'round': number, 'phase': 1,
                             'base_sha': base, 'head_sha': head, 'inputs': {}})
    old_rows = (over / 'ledger.jsonl').read_bytes()
    over_run = host('legacy-over-budget')
    results.append(check('legacy-thirteen-readable-but-new-launch-refused',
                         len(ledger.audit(over, repo)[0]) == 13 and over_run.returncode == 11
                         and (over / 'ledger.jsonl').read_bytes() == old_rows
                         and not (over / 'round-0014').exists()))
    budget_results = [host('three').returncode for _ in range(4)]
    results.append(check('third-recorded-round-handoffs-and-fourth-does-not-launch',
                         budget_results == [10, 10, 11, 11]
                         and len(ledger.audit(root('three'), repo)[0]) == 3
                         and not (root('three') / 'round-0004').exists()))
    bad = root('missing-prepared')
    bad.mkdir(parents=True)
    ledger.append(bad, {'event': 'started', 'round': 1, 'mode': ledger.MODE,
                        'phase': 1, 'base_sha': base, 'head_sha': head, 'inputs': {}})
    ledger.append(bad, {'event': 'finished', 'round': 1, 'executed': True,
                        'recorded': False, 'outputs': {}, 'guards': []})
    try:
        ledger.audit(bad, repo)
    except Rejected as error:
        missing_prepared = 'prepared' in str(error)
    else:
        missing_prepared = False
    results.append(check('executed-v3-without-prepared-rejected', missing_prepared))
    spec = importlib.util.spec_from_file_location('runner', SCRIPTS / 'lib/run-review.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    real_run = runner.run
    for label, failing, events_expected in [
        ('renderer-failure', 'render-prompt.py', ['started', 'finished']),
        ('clone-failure', 'clone', ['started', 'prepared', 'finished'])]:
        def failed_run(args, **kwargs):
            if (failing == 'render-prompt.py' and 'render-prompt.py' in str(args[1])) or (
                    failing == 'clone' and args[:2] == ['git', 'clone']):
                return subprocess.CompletedProcess(args, 1, b'', b'test failure')
            return real_run(args, **kwargs)
        with patch.dict(os.environ, env, clear=True), patch.object(runner, 'run', failed_run), \
                redirect_stderr(io.StringIO()):
            result = runner.main(['1', str(repo), head, label, base, 'stub'])
        failed_root = root(label)
        failed_rows = ledger.read(failed_root)
        results.append(check(label + '-preserves-only-observed-preparation',
                             result == 5 and [row['event'] for row in failed_rows] == events_expected
                             and not failed_rows[-1]['executed']
                             and not failed_rows[-1]['recorded']
                             and not (failed_root / 'round-0001/events.jsonl').exists()))

sys.exit(0 if all(results) else 1)
