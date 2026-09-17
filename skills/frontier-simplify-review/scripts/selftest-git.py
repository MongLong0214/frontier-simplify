import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'lib'))
import protocol
import ledger
import replay


class GitContextTests(unittest.TestCase):
    def test_git_uses_explicit_repository_without_changing_parent(self):
        with tempfile.TemporaryDirectory(prefix='review-git-') as temp:
            repos = [Path(temp) / name for name in ('a', 'b')]
            clean = {key: value for key, value in os.environ.items()
                     if not key.startswith(('GIT_', 'REVIEW_'))}
            heads = []
            for repo in repos:
                subprocess.run(['git', 'init', '-q', str(repo)], env=clean, check=True)
                subprocess.run(['git', '-C', str(repo), '-c', 'user.name=test',
                                '-c', 'user.email=test@example.invalid', 'commit',
                                '--allow-empty', '-qm', repo.name], env=clean, check=True)
                heads.append(subprocess.check_output(
                    ['git', '-C', str(repo), 'rev-parse', 'HEAD'], env=clean))
            with patch.dict(os.environ, GIT_DIR=str(repos[1] / '.git')):
                before = dict(os.environ)
                self.assertEqual(protocol.git(repos[0], 'rev-parse', 'HEAD'), heads[0])
                self.assertEqual(dict(os.environ), before)


class LiteralPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='review-paths-')
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / 'repo'
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith(('GIT_', 'REVIEW_'))}
        self.git('init', '-q', str(self.repo), outside=True)
        self.git('config', 'user.name', 'test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.paths = ['*.txt', 'one.txt', 'a?.txt', 'aa.txt', '[ab].txt', 'a.txt',
                      ':(glob)*', ' leading.txt', 'trailing.txt ', '한글\t:,file.txt']
        for index, name in enumerate(self.paths):
            (self.repo / name).write_text(f'old-{index}\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'before')
        self.base = self.git('rev-parse', 'HEAD').decode().strip()
        for index, name in enumerate(self.paths):
            (self.repo / name).write_text(f'new-{index}\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'after')
        self.head = self.git('rev-parse', 'HEAD').decode().strip()

    def git(self, *args, outside=False):
        command = ['git'] + ([] if outside else ['-C', str(self.repo)])
        return subprocess.check_output(command + list(args), env=self.env, stderr=subprocess.PIPE)

    def test_hunks_bind_only_the_literal_file(self):
        rows = protocol.hunks(self.repo, self.base, self.head)
        for name in self.paths:
            with self.subTest(name=name):
                patch_bytes = self.git('--literal-pathspecs', 'diff', '--no-color', '--no-ext-diff',
                                       '--no-textconv', '--no-renames', '--binary', '--unified=0',
                                       self.base, self.head, '--', name)
                identity = b'\0'.join([self.base.encode(), self.head.encode(), name.encode(), patch_bytes])
                selected = [row for row in rows if row['path'] == name]
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]['id'], 'H-' + protocol.digest(identity)[:20])
        self.assertEqual(set(protocol.changed(self.repo, self.base, self.head)), set(self.paths))

    def test_color_config_cannot_change_machine_hunks(self):
        expected = protocol.hunks(self.repo, self.base, self.head)
        self.git('config', 'color.ui', 'always')
        self.assertEqual(protocol.hunks(self.repo, self.base, self.head), expected)

    def test_conflicting_pathspec_environment_is_local(self):
        expected = protocol.hunks(self.repo, self.base, self.head)
        with patch.dict(os.environ, GIT_LITERAL_PATHSPECS='1', GIT_GLOB_PATHSPECS='1',
                        GIT_NOGLOB_PATHSPECS='1', GIT_ICASE_PATHSPECS='1'):
            before = dict(os.environ)
            self.assertEqual(protocol.hunks(self.repo, self.base, self.head), expected)
            self.assertEqual(dict(os.environ), before)

    def test_user_glob_keeps_pattern_semantics(self):
        actual = protocol.git(self.repo, 'diff', '--name-only', '-z', self.base, self.head, '--', '*.txt')
        self.assertIn(b'one.txt', actual.split(b'\0'))

    def test_unsupported_newline_path_is_rejected(self):
        (self.repo / 'line\nbreak').write_text('new\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'newline')
        with self.assertRaises(protocol.Rejected):
            protocol.changed(self.repo, self.head, 'HEAD')

    def test_host_children_drop_large_review_text(self):
        spec = importlib.util.spec_from_file_location('runner', SCRIPTS / 'lib/run-review.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with patch.dict(os.environ, REVIEW_HISTORY='x' * 262144, REVIEW_TEST_SCRIPTS='fixture'):
            before = dict(os.environ)
            result = runner.run([sys.executable, '-c',
                                 'import os,json; print(json.dumps(dict(os.environ)))'])
            received = json.loads(result.stdout)
            self.assertFalse('REVIEW_HISTORY' in received)
            self.assertEqual(received['REVIEW_TEST_SCRIPTS'], 'fixture')
            self.assertEqual(received['PATH'], os.environ['PATH'])
            self.assertEqual(dict(os.environ), before)


if __name__ == '__main__':
    unittest.main()
