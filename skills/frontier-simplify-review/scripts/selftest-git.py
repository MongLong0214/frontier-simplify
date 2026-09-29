import importlib.util
import io
import json
import os
import contextlib
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

    def test_adapter_and_executor_use_the_requested_checkout(self):
        with tempfile.TemporaryDirectory(prefix='review-adapter-') as temp:
            root = Path(temp).resolve()
            clean = protocol.child_environment()
            repo, other = root / 'source', root / 'other'
            def git(target, *args):
                return subprocess.check_output(['git', '-C', str(target), *args], env=clean)
            for target in (repo, other):
                target.mkdir()
                git(target, 'init', '-q')
                git(target, 'config', 'user.name', 'test')
                git(target, 'config', 'user.email', 'test@example.invalid')
                (target / 'a.txt').write_text(target.name + '\n')
                git(target, 'add', '.')
                git(target, 'commit', '-qm', 'base')
            base = git(repo, 'rev-parse', 'HEAD').decode().strip()
            (repo / 'a.txt').write_text('changed\n')
            git(repo, 'commit', '-qam', 'head')
            head = git(repo, 'rev-parse', 'HEAD').decode().strip()
            git(repo, 'remote', 'add', 'origin', str(repo))
            git(other, 'remote', 'add', 'origin', str(root / 'unrelated'))
            other_origin = git(other, 'remote', 'get-url', 'origin')
            source_entries = git(repo, 'ls-files', '--stage', '-z')
            linked = root / 'linked'
            git(repo, 'worktree', 'add', '--quiet', '--detach', str(linked), head)
            fakebin = root / 'bin'
            fakebin.mkdir()
            metadata = json.dumps({'number': 42, 'headRefOid': head, 'baseRefOid': base,
                                   'url': 'https://example.invalid/pull/42'})
            (fakebin / 'gh').write_text('#!' + sys.executable + '\n' +
                'import os,subprocess\n' +
                'assert "REVIEW_HISTORY" not in os.environ\n' +
                'assert subprocess.check_output(["git","rev-parse","HEAD"]).decode().strip() == ' + repr(head) + '\n' +
                'print(' + repr(metadata) + ')\n')
            (fakebin / 'codex').write_text('#!' + sys.executable + '\n' +
                'import os,subprocess,json\n' +
                'assert not any(k.startswith("REVIEW_") for k in os.environ)\n' +
                'assert subprocess.check_output(["git","rev-parse","HEAD"]).decode().strip() == ' + repr(head) + '\n' +
                'print(json.dumps({"type":"item.completed","item":{"type":"command_execution","command":"git rev-parse HEAD"}}))\n' +
                'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"Requested checkout inspected."}}))\n' +
                'print(json.dumps({"type":"turn.completed"}))\n')
            for executable in fakebin.iterdir():
                executable.chmod(0o755)
            spec = importlib.util.spec_from_file_location('adapter', SCRIPTS / 'lib/review-pr.py')
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
            for routing in (str(other / '.git'), '../other/.git'):
                with self.subTest(routing=routing), patch.dict(os.environ, clean, clear=True):
                    os.environ.update(PATH=str(fakebin) + os.pathsep + clean['PATH'],
                                      GIT_DIR=routing, REVIEW_HISTORY='x' * 262144,
                                      GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='color.ui', GIT_CONFIG_VALUE_0='always',
                                      REVIEW_ARTIFACTS=str(root / ('artifacts-' + str(len(routing)))))
                    before = dict(os.environ)
                    with patch.object(sys, 'argv', ['review-pr.py', str(linked), '42', 'auto', 'codex']), contextlib.redirect_stdout(io.StringIO()):
                        self.assertEqual(adapter.main(), 10)
                    directory = next(Path(os.environ['REVIEW_ARTIFACTS']).rglob('round-0001'))
                    expected = git(repo, 'diff', '--no-color', '--no-ext-diff', '--no-textconv',
                                   '--no-renames', '--binary', base, head)
                    self.assertEqual((directory / 'DIFF.patch').read_bytes(), expected)
                    self.assertEqual(replay.replay(directory.parent, repo, base, head, io.StringIO()), 10)
                    # Adapter-owned metadata may change; inherited routing stays intact.
                    self.assertEqual(os.environ['GIT_DIR'], before['GIT_DIR'])
                    self.assertEqual(git(linked, 'rev-parse', 'HEAD').decode().strip(), head)
                    self.assertEqual(git(other, 'remote', 'get-url', 'origin'), other_origin)
                    self.assertFalse((other / '.git/FETCH_HEAD').exists())
                    self.assertEqual(git(repo, 'ls-files', '--stage', '-z'), source_entries)
                    self.assertEqual((repo / 'a.txt').read_bytes(), b'changed\n')


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

    def test_both_rounds_and_replay_keep_uncolored_patches(self):
        spec = importlib.util.spec_from_file_location('runner', SCRIPTS / 'lib/run-review.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        root = Path(self.temp.name)
        events = root / 'events.jsonl'
        events.write_text('\n'.join(json.dumps(row) for row in [
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'command': 'git diff'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Patch inspected.'}},
            {'type': 'turn.completed'}]) + '\n')
        with patch.dict(os.environ, self.env, clear=True):
            os.environ.update(REVIEW_ARTIFACTS=str(root / 'artifacts'), REVIEW_STUB=str(events),
                              GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='color.ui', GIT_CONFIG_VALUE_0='always')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(['1', str(self.repo), self.head, 'color', self.base, 'stub']), 10)
                (self.repo / 'one.txt').write_text('repair\n')
                self.git('commit', '-qam', 'repair')
                repair = self.git('rev-parse', 'HEAD').decode().strip()
                self.assertEqual(runner.main(['2', str(self.repo), repair, 'color', self.base, 'stub']), 10)
            directory = runner.root_for(self.repo, 'color')
            for filename, before in [('DIFF.patch', self.base), ('REMEDIATION.patch', self.head)]:
                expected = self.git('diff', '--no-color', '--no-ext-diff', '--no-textconv',
                                    '--no-renames', '--binary', before, repair)
                self.assertEqual((directory / 'round-0002' / filename).read_bytes(), expected)
            self.assertEqual(replay.replay(directory, self.repo, self.base, repair, io.StringIO()), 10)

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
