#!/usr/bin/env python3
"""Installed host hook: test the staged tree using an independently installed test suite."""
import os
from pathlib import Path
import subprocess

# Scrub the hook's OWN environment first, not only the child's. Git exports GIT_DIR and
# GIT_INDEX_FILE into a hook, and every git command this file runs -- including the ones that read
# the staged tree -- inherits them. Passing a cleaned env to one subprocess left this process
# itself pointed at the outer index, and a commit that took a second by hand took minutes through
# git. Measured both ways: 0s invoked directly, over 120s with GIT_DIR set.
for _leaked in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_PREFIX', 'GIT_COMMON_DIR',
                'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES'):
    os.environ.pop(_leaked, None)
import sys
import tarfile
import tempfile


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def check(repo, trusted):
    changed = subprocess.check_output(['git', '-C', str(repo), 'diff', '--cached', '--name-only', '-z'])
    if not any(p.startswith(b'skills/sol-simplify-review/') for p in changed.split(b'\0')):
        return
    # The index tree is one Git snapshot; tests cannot validate unstaged replacement bytes.
    tree = git(repo, 'write-tree')
    with tempfile.TemporaryDirectory(prefix='review-commit-') as tmp:
        tmp = Path(tmp).resolve()
        archive = tmp / 'index.tar'
        subprocess.run(['git', '-C', str(repo), 'archive', '--format=tar', '-o', str(archive), tree], check=True)
        staged = tmp / 'staged'
        staged.mkdir()
        with tarfile.open(archive) as tar:
            for member in tar:
                path = staged / member.name
                if not path.resolve().is_relative_to(staged) or member.issym() or member.islnk():
                    # Unrelated symlinks are not needed to test the portable skill.
                    if member.name.startswith('skills/sol-simplify-review/'):
                        raise ValueError('skill code must be regular files in the staged snapshot')
                    continue
                tar.extract(member, staged)
        candidate = staged / 'skills/sol-simplify-review/scripts'
        env = dict(os.environ, REVIEW_TEST_SCRIPTS=str(candidate), PYTHONDONTWRITEBYTECODE='1')
        env.pop('REVIEW_TEST_SKIP', None)
        # The hook runs the fast half. It ran the whole suite twice -- once for the
        # installed copy, once for the staged one -- and the suite grew from 34 cases to 164
        # in a day, so a commit took minutes and every one of them was interrupted. A hook
        # that slow is a hook somebody switches off, which is the failure this file's own
        # comments warn about. The slow half builds repositories and drives whole rounds;
        # it belongs where waiting costs nothing, and it says out loud that it skipped it.
        env['REVIEW_SELFTEST_FAST'] = '1'
        # Git exports GIT_DIR, GIT_INDEX_FILE and friends into every hook, and they follow any git
        # command the hook starts -- including the ones the suite runs inside the throwaway
        # repository it builds to measure itself. Measured: with GIT_DIR set, `git worktree add`
        # in the fixture lands somewhere else and the seal/head cross-check fails, so the gate
        # blocked a commit and named a guard that had nothing to do with the change. A gate that
        # reports the wrong reason is worse than one that stays quiet.
        for leaked in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_PREFIX',
                       'GIT_COMMON_DIR', 'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES'):
            env.pop(leaked, None)
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
                                str(candidate.parent), str(config)], capture_output=True, text=True)
            if p.returncode:
                raise ValueError(p.stderr.strip())
        if git(repo, 'write-tree') != tree:
            raise ValueError('index changed during selftest; retry the commit')
    print('review-selftest: staged snapshot passed installed and staged suites')


if __name__ == '__main__':
    try:
        check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        sys.exit('review-selftest: ' + str(e).replace('\n', '; '))
