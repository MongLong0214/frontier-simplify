#!/usr/bin/env python3
"""Observe the owned checkout before deletion without inventing legacy observations."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'lib'))
import ledger
import replay
from protocol import Rejected


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def check(name, good):
    print(('ok   ' if good else 'NOT OK ') + name)
    return good


with tempfile.TemporaryDirectory(prefix='review-observe-test-') as temporary:
    t = Path(temporary)
    repo = t / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    (repo / 'source.txt').write_text('before\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'source.txt').write_text('after\n')
    git(repo, 'commit', '-qam', 'head')
    head = git(repo, 'rev-parse', 'HEAD')
    fixture = t / 'events.jsonl'
    fixture.write_text('\n'.join(json.dumps(event) for event in [
        {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'cat source.txt'}},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Reviewed source.txt'}},
        {'type': 'turn.completed'}]) + '\n')
    fakebin = t / 'bin'
    fakebin.mkdir()
    executable = fakebin / 'codex'
    executable.write_text('#!' + sys.executable + '\n' + '''
import os, shutil, subprocess, sys
from pathlib import Path
mode = os.environ['TEST_MODE']
source = Path('source.txt')
if mode == 'tracked':
    source.write_text('changed in checkout\\n')
elif mode == 'staged':
    source.write_text('staged only\\n')
    subprocess.run(['git', 'add', 'source.txt'], check=True)
    source.write_bytes(subprocess.check_output(['git', 'show', 'HEAD:source.txt']))
elif mode == 'executable':
    source.chmod(0o755)
elif mode == 'symlink':
    source.unlink()
    source.symlink_to('missing-target')
elif mode == 'input':
    Path('DIFF.patch').write_text('changed input')
elif mode == 'input-delete':
    Path('DIFF.patch').unlink()
elif mode == 'input-symlink':
    Path('DIFF.patch').unlink()
    Path('DIFF.patch').symlink_to('source.txt')
elif mode == 'untracked':
    Path('generated.out').write_text('allowed output')
elif mode == 'index-cache':
    source.touch()
    subprocess.run(['git', 'update-index', '--refresh'], check=True)
elif mode == 'experiment':
    copy = os.environ['TEST_EXPERIMENT']
    shutil.copytree(os.getcwd(), copy)
    Path(copy, 'source.txt').write_text('changed only in experiment')
elif mode == 'head':
    subprocess.run(['git', 'checkout', '--quiet', '--detach', os.environ['TEST_BASE']], check=True)
elif mode == 'clone-gone':
    shutil.rmtree(os.getcwd())
sys.stdout.write(Path(os.environ['TEST_EVENTS']).read_text())
''')
    executable.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith('REVIEW_')}
    env.update(PATH=str(fakebin) + os.pathsep + env['PATH'],
               REVIEW_ARTIFACTS=str(t / 'artifacts'), TEST_EVENTS=str(fixture), TEST_BASE=base,
               TEST_EXPERIMENT=str(t / 'experiment'),
               PYTHONDONTWRITEBYTECODE='1')
    def host(mode):
        return subprocess.run([str(SCRIPTS / 'review-round.sh'), '1', str(repo), head, mode,
                               base, 'codex'], env=dict(env, TEST_MODE=mode),
                              capture_output=True, text=True)
    def root(mode):
        return Path(subprocess.check_output([str(SCRIPTS / 'review-round.sh'), 'path',
                    str(repo), head, mode, base], env=env).decode().strip())
    def receipt(mode):
        return ledger.read(root(mode))[-1]
    results = []
    clean = host('clean')
    observations = receipt('clean').get('checkout_observations', {})
    results.append(check('clean-primary-has-three-real-observations',
                         clean.returncode == 10
                         and ledger.read(root('clean'))[0].get('checkout_checks_version') == 1
                         and observations.get('head', {}).get('observed_sha') == head
                         and all(observations.get(key, {}).get('status') == 'unchanged'
                                 for key in ('head', 'tracked', 'input_copies'))))
    for mode, field in [('tracked', 'tracked'), ('staged', 'tracked'),
                        ('executable', 'tracked'), ('symlink', 'tracked'),
                        ('input', 'input_copies'), ('input-delete', 'input_copies'),
                        ('input-symlink', 'input_copies'), ('head', 'head')]:
        run = host(mode)
        end = receipt(mode)
        results.append(check(mode + '-is-physical-failure-not-recorded',
                             run.returncode == 5 and not end.get('recorded')
                             and end.get('checkout_observations', {}).get(field, {}).get('status') == 'changed'))
    cached_rows = (root('tracked') / 'ledger.jsonl').read_bytes()
    cached_failure = subprocess.run([str(SCRIPTS / 'review-round.sh'), 'auto', str(repo), head,
                                     'tracked', base, 'codex'], env=dict(env, TEST_MODE='tracked'),
                                    capture_output=True, text=True)
    results.append(check('physical-failure-is-not-cached-success-or-retried',
                         cached_failure.returncode == 5
                         and (root('tracked') / 'ledger.jsonl').read_bytes() == cached_rows))
    for mode in ('untracked', 'index-cache', 'experiment'):
        run = host(mode)
        results.append(check(mode + '-is-allowed',
                             run.returncode == 10 and receipt(mode).get('recorded')))
    missing = host('clone-gone')
    results.append(check('missing-clone-is-observed-error',
                         missing.returncode == 5 and not receipt('clone-gone').get('recorded')
                         and any(part.get('status') == 'error' for part in
                                 receipt('clone-gone').get('checkout_observations', {}).values())))
    spec = importlib.util.spec_from_file_location('runner', SCRIPTS / 'lib/run-review.py')
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    replaced = t / 'replaced-clone'
    replaced.symlink_to(repo, target_is_directory=True)
    symlink_observations = runner.observe_checkout(replaced, head, t, [], {})
    results.append(check('replaced-checkout-path-never-follows-symlink',
                         all(item['status'] == 'error' for item in symlink_observations.values())
                         and replaced.is_symlink()))
    for mode, expected in [('clean', 'UNCHANGED'), ('tracked', 'CHANGED'),
                           ('clone-gone', 'ERROR')]:
        replay_output = io.StringIO()
        try:
            replay_code = replay.replay(root(mode), repo, base, head, replay_output)
        except Rejected:
            replay_code = 5
        results.append(check(mode + '-replay-preserves-stored-observation',
                             replay_code == (10 if mode == 'clean' else 5)
                             and 'checkout=' + expected in replay_output.getvalue()))
    if clean.returncode == 10:
        def history(label, transform):
            destination = t / label
            shutil.copytree(root('clean'), destination)
            rows = ledger.read(destination)
            transform(rows)
            (destination / 'ledger.jsonl').unlink()
            for row in rows:
                ledger.append(destination, row)
            return destination
        legacy = history('legacy', lambda rows: (
            rows[0].pop('checkout_checks_version', None),
            rows[-1].pop('checkout_observations', None)))
        old_bytes = (legacy / 'ledger.jsonl').read_bytes()
        report = io.StringIO()
        result = replay.replay(legacy, repo, base, head, report)
        results.append(check('legacy-without-observations-remains-available-and-labelled',
                             result == 10 and 'NOT_OBSERVED' in report.getvalue()
                             and (legacy / 'ledger.jsonl').read_bytes() == old_bytes))
        declared = history('declared-missing', lambda rows: rows[-1].pop('checkout_observations', None))
        try:
            ledger.audit(declared, repo)
        except Rejected as error:
            rejected = 'observation' in str(error)
        else:
            rejected = False
        results.append(check('declared-missing-observations-refused', rejected))
    else:
        results += [False, False]

sys.exit(0 if all(results) else 1)
