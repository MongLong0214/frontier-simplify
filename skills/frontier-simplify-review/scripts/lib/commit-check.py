#!/usr/bin/env python3
"""Installed host hook: test the staged tree using an independently installed test suite."""
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from protocol import child_environment


def git(repo, *args, env=None):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE,
                                   env=child_environment() if env is None else env).decode().strip()


def check(repo, trusted):
    # Git's temporary index (including commit --only) belongs to the source, not the
    # test checkout. Relative overrides are relative to the hook's actual cwd.
    explicit = os.environ.get('GIT_INDEX_FILE')
    if explicit is not None:
        index = Path(os.path.abspath(explicit))
        with index.open('rb'):
            pass
    else:
        index = Path(git(repo, 'rev-parse', '--git-path', 'index'))
        if not index.is_absolute():
            index = repo / index
    source_env = dict(child_environment(), GIT_INDEX_FILE=str(index))
    changed = subprocess.check_output(['git', '-C', str(repo), 'diff', '--cached', '--name-only', '-z'],
                                      env=source_env, stderr=subprocess.PIPE)
    if not any(p.startswith(b'skills/frontier-simplify-review/') for p in changed.split(b'\0')):
        return
    # The index tree is one Git snapshot; tests cannot validate unstaged replacement bytes.
    tree = git(repo, 'write-tree', env=source_env)
    with tempfile.TemporaryDirectory(prefix='review-commit-') as tmp:
        tmp = Path(tmp).resolve()
        archive = tmp / 'index.tar'
        # Only the skill's own subtree. Archiving the whole index copied 8MB of repository on
        # every commit -- benchmarks included -- to test a directory that is 276KB of it. The
        # snapshot is still one Git tree, so what the tests read is still exactly what is staged.
        subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar', '-o', str(archive),
                        tree, 'skills/frontier-simplify-review'], env=child_environment(), check=True)
        staged = tmp / 'staged'
        staged.mkdir()
        with tarfile.open(archive) as tar:
            for member in tar:
                path = staged / member.name
                if not path.resolve().is_relative_to(staged) or member.issym() or member.islnk():
                    # Unrelated symlinks are not needed to test the portable skill.
                    if member.name.startswith('skills/frontier-simplify-review/'):
                        raise ValueError('skill code must be regular files in the staged snapshot')
                    continue
                tar.extract(member, staged)
        candidate = staged / 'skills/frontier-simplify-review/scripts'
        env = dict(child_environment(), REVIEW_TEST_SCRIPTS=str(candidate), PYTHONDONTWRITEBYTECODE='1')
        env.pop('REVIEW_TEST_SKIP', None)
        # The hook runs the fast half. It ran the whole suite twice -- once for the
        # installed copy, once for the staged one -- and the suite grew from 34 cases to 164
        # in a day, so a commit took minutes and every one of them was interrupted. A hook
        # that slow is a hook somebody switches off, which is the failure this file's own
        # comments warn about. The slow half builds repositories and drives whole rounds;
        # it belongs where waiting costs nothing, and it says out loud that it skipped it.
        env['REVIEW_SELFTEST_FAST'] = '1'
        config = trusted / 'consumers.json'
        if config.exists():
            env['REVIEW_CONSUMERS_CONFIG'] = str(config)
        # Stored pass files and candidate test edits cannot replace these host-owned tests.
        for label, suite in [('installed', trusted / 'scripts/selftest.sh'), ('staged', candidate / 'selftest.sh')]:
            p = subprocess.run(['bash', str(suite)], cwd=staged, env=env, capture_output=True, text=True)
            if p.returncode:
                reason = next((line for line in (p.stdout + p.stderr).splitlines()
                               if 'NOT OK' in line or 'GUARD FAIL' in line), '')
                raise ValueError(f'{label} suite failed: {reason or (p.stderr.strip().splitlines() or ["see selftest.sh"])[-1]}')
        if config.exists():
            p = subprocess.run([sys.executable, str(trusted / 'scripts/lib/portability.py'),
                                str(candidate.parent), str(config)], capture_output=True, text=True,
                               env=child_environment())
            if p.returncode:
                raise ValueError(p.stderr.strip())
        if git(repo, 'write-tree', env=source_env) != tree:
            raise ValueError('index changed during selftest; retry the commit')
    print('review-selftest: staged snapshot passed installed and staged suites')


if __name__ == '__main__':
    try:
        check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        sys.exit('review-selftest: ' + str(e).replace('\n', '; '))
