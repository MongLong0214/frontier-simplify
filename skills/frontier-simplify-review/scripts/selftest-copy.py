#!/usr/bin/env python3
"""No-clobber input installation and ordinary seal-like source regression."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'lib'))
import ledger
from protocol import Rejected

spec = importlib.util.spec_from_file_location('run_review', SCRIPTS / 'lib/run-review.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def check(name, fn):
    try:
        assert fn(), name
    except (AssertionError, OSError, Rejected) as error:
        print(f'NOT OK {name}: {error}')
        return False
    print(f'ok   {name}')
    return True


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def collision(source, target):
    try:
        runner.copy_input(source, target.parent, target.name)
    except Rejected as error:
        return '[input-collision]' in str(error)
    return False


with tempfile.TemporaryDirectory(prefix='review-copy-test-') as temporary:
    t = Path(temporary)
    source = t / 'source'
    source.write_bytes(b'\x00literal input\xff\n')
    dest = t / 'clone'
    dest.mkdir()
    target = dest / 'DIFF.patch'
    passed = []
    passed.append(check('absent-target-preserves-exact-bytes',
                        lambda: (runner.copy_input(source, dest, target.name) is None
                                 and target.read_bytes() == source.read_bytes())))
    passed.append(check('existing-regular-refused-without-overwrite',
                        lambda: collision(source, target) and target.read_bytes() == source.read_bytes()))
    target.unlink()
    target.mkdir()
    passed.append(check('existing-directory-refused', lambda: collision(source, target) and target.is_dir()))
    target.rmdir()
    outside = t / 'outside'
    target.symlink_to(outside)
    passed.append(check('dangling-symlink-does-not-create-outside-file',
                        lambda: collision(source, target) and target.is_symlink() and not outside.exists()))
    target.unlink()
    outside.write_bytes(b'owned bytes')
    target.symlink_to(outside)
    passed.append(check('live-symlink-does-not-overwrite-outside-file',
                        lambda: collision(source, target) and outside.read_bytes() == b'owned bytes'))
    target.unlink()
    real_open = Path.open
    def raced_open(path, mode='r', *args, **kwargs):
        if path == target and mode == 'xb':
            target.write_bytes(b'race winner')
        return real_open(path, mode, *args, **kwargs)
    with patch.object(Path, 'open', raced_open):
        passed.append(check('check-create-race-still-refuses-overwrite',
                            lambda: collision(source, target) and target.read_bytes() == b'race winner'))

    repo = t / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    (repo / 'source.py').write_text('print("before")\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'source.py').write_text("print('target_sha256: ' + value)\n")
    (repo / 'fixtures').mkdir()
    (repo / 'fixtures/SEAL.txt').write_text('schema: frontier-simplify-review-seal.v1\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'source fixtures')
    head = git(repo, 'rev-parse', 'HEAD')
    events = t / 'events'
    events.write_text('\n'.join(json.dumps(row) for row in [
        {'type': 'item.completed', 'item': {'type': 'command_execution',
         'command': 'cat source.py fixtures/SEAL.txt',
         'aggregated_output': "print('target_sha256: ' + value)\nschema: frontier-simplify-review-seal.v1"}},
        {'type': 'item.completed', 'item': {'type': 'agent_message',
         'text': 'The fixture names target_sha256; source behavior was reviewed.'}},
        {'type': 'turn.completed'}]) + '\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith('REVIEW_')}
    env.update(REVIEW_ARTIFACTS=str(t / 'artifacts'), REVIEW_STUB=str(events),
               PYTHONDONTWRITEBYTECODE='1')
    def host(phase, pr='marker'):
        return subprocess.run([str(SCRIPTS / 'review-round.sh'), phase, str(repo), head, pr, base, 'stub'],
                              env=env, capture_output=True, text=True)
    marker = host('1')
    root = Path(host('path').stdout.strip())
    passed.append(check('normal-marker-source-and-repo-seal-record',
                        lambda: marker.returncode == 10 and ledger.audit(root, repo)[1][1]['recorded']))
    events.write_text('\n'.join(json.dumps(row) for row in [
        {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash',
         'input': {'command': 'cat source.py fixtures/SEAL.txt'}}]}},
        {'type': 'assistant', 'message': {'content': [{'type': 'text',
         'text': 'The fixture contains schema: frontier-simplify-review-seal.v1 and target_sha256.'}]}},
        {'type': 'result', 'subtype': 'success'}]) + '\n')
    claude_marker = host('1', 'claude-marker')
    claude_root = Path(host('path', 'claude-marker').stdout.strip())
    passed.append(check('claude-marker-event-records',
                        lambda: claude_marker.returncode == 10
                        and ledger.audit(claude_root, repo)[1][1]['recorded']))
    if marker.returncode == 10:
        rows = ledger.read(root)
        rows[0]['skill_sha256'] = 'older-protocol'
        rows[-1]['guards'].append({'guard': 'guard_seal_unseen', 'ok': False,
                                  'reason': 'historical marker-only refusal'})
        rows[-1]['recorded'] = False
        (root / 'ledger.jsonl').unlink()
        for row in rows:
            ledger.append(root, row)
        preserved = (root / 'ledger.jsonl').read_bytes()
        passed.append(check('historical-marker-failure-remains-failure',
                            lambda: not ledger.audit(root, repo)[1][1]['recorded']
                            and bool(ledger.audit(root, repo)[2])
                            and (root / 'ledger.jsonl').read_bytes() == preserved
                            and host('auto').returncode == 5))
    else:
        print('NOT OK historical-marker-failure-remains-failure: preceding round did not record')
        passed.append(False)

    # The installed runner must refuse a collision before entering the executor.
    (repo / 'DIFF.patch').symlink_to(t / 'new-outside')
    git(repo, 'add', 'DIFF.patch')
    git(repo, 'commit', '-qm', 'colliding input')
    head = git(repo, 'rev-parse', 'HEAD')
    collision_run = host('1', 'collision')
    collision_root = Path(host('path', 'collision').stdout.strip())
    passed.append(check('runner-rejects-dangling-clone-input-before-execution',
                        lambda: collision_run.returncode == 5
                        and '[input-collision]' in collision_run.stderr
                        and not (t / 'new-outside').exists()
                        and not ledger.audit(collision_root, repo)[1][1]['executed']))

sys.exit(0 if all(passed) else 1)
