"""Real installed-hook checks for source index selection and staged-tree semantics."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'lib'))
from protocol import child_environment


class SourceIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='review-index-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.env = child_environment()
        self.git('init', '-q')
        self.git('config', 'user.name', 'test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.relative = 'skills/frontier-simplify-review/scripts/probe.sh'
        self.candidate = self.repo / 'skills/frontier-simplify-review/scripts'
        self.candidate.mkdir(parents=True)
        self.probe = self.repo / self.relative
        self.probe.write_text('echo good\n')
        (self.candidate / 'selftest.sh').write_text('#!/bin/sh\nexit 0\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'seed')
        self.run_command([str(SCRIPTS / 'install-hook.sh'), str(self.repo)], check=True)
        self.trusted = self.repo / '.git/hooks/frontier-simplify-review'
        self.suite = self.trusted / 'scripts/selftest.sh'
        self.suite.write_text('''#!/bin/sh
set -eu
[ "${GIT_INDEX_FILE+x}" != x ] || { echo 'NOT OK source index leaked'; exit 1; }
[ "$(bash "$REVIEW_TEST_SCRIPTS/probe.sh")" = good ] || { echo 'NOT OK staged defect'; exit 1; }
''')

    def run_command(self, args, env=None, check=False):
        return subprocess.run(args, cwd=self.repo, env=self.env if env is None else env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check)

    def git(self, *args, env=None):
        return self.run_command(['git', *args], env=env, check=True).stdout

    def alternate(self, relative=False):
        index = self.repo / 'alternate-index'
        env = dict(self.env, GIT_INDEX_FILE=index.name if relative else str(index))
        self.git('read-tree', 'HEAD', env=env)
        return env

    def rejected_commit(self, env=None, only=False):
        before = self.git('rev-parse', 'HEAD')
        entries = self.git('ls-files', '--stage', '-z', env=env)
        working = self.probe.read_bytes()
        args = ['git', 'commit', '-qm', 'candidate'] + (['--only', self.relative] if only else [])
        result = self.run_command(args, env=env)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('staged defect', result.stderr)
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual(self.git('ls-files', '--stage', '-z', env=env), entries)
        self.assertEqual(self.probe.read_bytes(), working)

    def stage_defect(self, env=None):
        self.probe.write_text('echo bad\n')
        self.git('add', self.relative, env=env)
        self.probe.write_text('echo good\n')

    def test_absolute_alternate_index_is_checked(self):
        env = self.alternate()
        self.stage_defect(env)
        self.rejected_commit(env)

    def test_relative_alternate_index_is_checked(self):
        env = self.alternate(relative=True)
        self.stage_defect(env)
        self.rejected_commit(env)

    def test_default_index_is_checked(self):
        self.stage_defect()
        self.rejected_commit()

    def test_alternate_does_not_validate_unrelated_default_index(self):
        env = self.alternate()
        self.stage_defect()
        default_entries = self.git('ls-files', '--stage', '-z')
        (self.candidate / 'selftest.sh').write_text('#!/bin/sh\nexit 0\n# alternate change\n')
        self.git('add', 'skills', env=env)
        result = self.run_command(['git', 'commit', '-qm', 'alternate'], env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('show', 'HEAD:' + self.relative), 'echo good\n')
        self.assertEqual(self.git('ls-files', '--stage', '-z'), default_entries)

    def test_commit_only_uses_its_temporary_index(self):
        self.probe.write_text('echo bad\n')
        self.rejected_commit(only=True)

    def test_linked_worktree_default_index(self):
        linked = self.root / 'linked'
        self.git('worktree', 'add', '--quiet', '-b', 'linked', str(linked))
        self.repo = linked
        self.probe = linked / self.relative
        self.stage_defect()
        self.rejected_commit()

    def test_linked_worktree_relative_alternate_index(self):
        linked = self.root / 'linked'
        self.git('worktree', 'add', '--quiet', '-b', 'linked', str(linked))
        self.repo = linked
        self.probe = linked / self.relative
        env = self.alternate(relative=True)
        self.stage_defect(env)
        self.rejected_commit(env)

    def driver_with_index_change(self, command):
        env = self.alternate()
        index = Path(env['GIT_INDEX_FILE'])
        (self.candidate / 'selftest.sh').write_text('#!/bin/sh\nexit 0\n# staged change\n')
        self.git('add', 'skills', env=env)
        entries = self.git('ls-files', '--stage', '-z', env=env)
        env.update(INDEX_FIXTURE=str(index), REPO_FIXTURE=str(self.repo),
                   BEFORE_FIXTURE=str(self.root / 'before-index'),
                   AFTER_FIXTURE=str(self.root / 'after-index'))
        self.suite.write_text(self.suite.read_text() +
                             'cp "$INDEX_FIXTURE" "$BEFORE_FIXTURE"\n' + command + '\n' +
                             'cp "$INDEX_FIXTURE" "$AFTER_FIXTURE"\n')
        result = self.run_command([sys.executable, str(self.trusted / 'scripts/lib/commit-check.py'),
                                   str(self.repo), str(self.trusted)], env=env)
        self.assertNotEqual((self.root / 'before-index').read_bytes(),
                            (self.root / 'after-index').read_bytes())
        return result, entries, env

    def test_index_cache_bytes_may_change_with_the_same_entries(self):
        result, entries, env = self.driver_with_index_change(
            'GIT_INDEX_FILE="$INDEX_FIXTURE" git -C "$REPO_FIXTURE" update-index --index-version=4')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('ls-files', '--stage', '-z', env=env), entries)

    def test_changed_index_tree_is_rejected_after_the_suite(self):
        result, entries, env = self.driver_with_index_change(
            'GIT_INDEX_FILE="$INDEX_FIXTURE" git -C "$REPO_FIXTURE" update-index --chmod=+x ' + self.relative)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('index changed during selftest', result.stderr)
        self.assertNotEqual(self.git('ls-files', '--stage', '-z', env=env), entries)

    def test_missing_explicit_index_is_not_default_fallback(self):
        env = dict(self.env, GIT_INDEX_FILE=str(self.root / 'missing'))
        result = self.run_command([sys.executable, str(self.trusted / 'scripts/lib/commit-check.py'),
                                   str(self.repo), str(self.trusted)], env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('index', result.stderr)

    def test_import_does_not_mutate_parent_environment(self):
        spec = importlib.util.spec_from_file_location('commit_check', SCRIPTS / 'lib/commit-check.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, GIT_INDEX_FILE='relative-index', GIT_DIR='other'):
            before = dict(os.environ)
            spec.loader.exec_module(module)
            self.assertTrue(dict(os.environ) == before, 'module import mutated parent environment')


if __name__ == '__main__':
    unittest.main()
