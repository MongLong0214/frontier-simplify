"""Actual subprocess boundaries for prompt rendering and finite reviewer stdin."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parent
RENDERER = SCRIPTS / 'lib/render-prompt.py'


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='review-render-')
        self.addCleanup(self.temp.cleanup)
        self.skill = Path(self.temp.name) / 'SKILL.md'
        self.skill.write_text('## Round 1 prompt\n\n```text\nA={{A}}; B={{B}}\n```\n')

    def render(self, *args, payload=None):
        return subprocess.run([sys.executable, str(RENDERER), str(self.skill), '1', *args],
                              input=payload, capture_output=True)

    def test_values_are_opaque_and_order_independent(self):
        values = {'A': '{{B}} $& 한글 ```', 'B': 'line 1\nline 2 \\ end'}
        expected = ('A=' + values['A'] + '; B=' + values['B'] + '\n').encode()
        for ordered in (values, dict(reversed(list(values.items())))):
            with self.subTest(ordered=list(ordered)):
                result = self.render('--values-stdin', payload=json.dumps(ordered).encode())
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
        legacy = self.render(*[f'{key}={value}' for key, value in values.items()])
        self.assertEqual(legacy.stdout, expected)

    def test_bad_inputs_fail_without_echoing_values(self):
        private = 'private-source-text'
        for args, payload in [
            (['A=' + private], None),
            (['--values-stdin', 'A=x'], b'{}'),
            (['--values-stdin'], b'{'),
            (['--values-stdin'], b'[]'),
            (['--values-stdin'], b'{"A":null,"B":"x"}'),
            (['--values-stdin'], b'{"A":"x","B":3}'),
            (['--values-stdin'], b'{"A":"x","A":"y","B":"z"}'),
            (['--values-stdin'], b'\xff'),
        ]:
            with self.subTest(args=args, payload=payload):
                result = self.render(*args, payload=payload)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(private.encode(), result.stderr)

    def test_real_round1_prompt_carries_investigation_guidance(self):
        self.skill = SCRIPTS.parent / 'SKILL.md'
        values = {'REPOSITORY': '한글 {{BASE_SHA}} ```', 'BASE_SHA': 'base',
                  'ROUND1_HEAD_SHA': 'head', 'REVIEW_BUDGET': 'automatic attempt 1 of 3',
                  'REQUIREMENT_SOURCES_OR_NONE': 'none', 'KNOWN_ROUTED_OR_NONE': 'none',
                  'PROJECT_CLASS_CATALOG_OR_NONE': 'none',
                  'FULL_SUITE_STATUS_OR_UNKNOWN': 'unknown', 'TOOL_NOTES_OR_NONE': 'none'}
        result = self.render('--values-stdin', payload=json.dumps(values).encode())
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = result.stdout.decode()
        self.assertIn(values['REPOSITORY'], prompt)
        for instruction in ('deleted file', 'old side', 'direct authority', 'sibling',
                            'falsification', 'line location', 'UNAVAILABLE',
                            'producer/sink table', 'could not enumerate', '- invariant: <KEY>',
                            'reproduce it there and classify it', 'excluding the path from the contract',
                            'review_evidence/<FINDING-ID>.sh'):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)
        self.assertIn('SCOPE.json', prompt)

    def test_real_round2_prompt_carries_followup_guidance(self):
        skill = SCRIPTS.parent / 'SKILL.md'
        values = {'REPOSITORY': 'repo', 'BASE_SHA': 'base', 'ROUND1_HEAD_SHA': 'original',
                  'ROUND2_HEAD_SHA': 'repair', 'TRUSTED_INVENTORY_SHA256': 'digest',
                  'INVENTORY_INTEGRITY_RESULT': 'ok', 'REVIEW_BUDGET': 'automatic attempt 2 of 3',
                  'REQUIREMENT_SOURCES_OR_NONE': 'none',
                  'KNOWN_ROUTED_OR_NONE': 'none', 'PROJECT_CLASS_CATALOG_OR_NONE': 'none',
                  'FULL_SUITE_STATUS_OR_UNKNOWN': 'unknown', 'TOOL_NOTES_OR_NONE': 'none',
                  'OPEN_INVARIANTS_OR_NONE': 'none', 'HOST_NOTES_OR_NONE': 'none'}
        result = subprocess.run([sys.executable, str(RENDERER), str(skill), '2',
                                 '--values-stdin'], input=json.dumps(values).encode(),
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = result.stdout.decode()
        for instruction in ('ROUND1_INVENTORY.md', 'PREVIOUS_REVIEW.md',
                            'IMPLEMENTER_RESPONSE.md', 'REMEDIATION.patch',
                            'response-only', 'unchanged caller', 'named witness',
                            'ROUND1-ESCAPE', 'UNAVAILABLE', 'IMPLEMENTER_REDESIGN.md',
                            'WITNESS_RESULTS.md', 'MISSED row', 'witness_obsolete',
                            'excluding the path from the contract', 'two consecutive reviews'):
            with self.subTest(instruction=instruction):
                self.assertIn(instruction, prompt)
        self.assertIn('SCOPE.json', prompt)


class ReviewStdinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='review-stdin-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.clean = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'REVIEW_'))}
        self.git('init', '-q')
        self.git('config', 'user.name', 'test')
        self.git('config', 'user.email', 'test@example.invalid')
        (self.repo / 'target.txt').write_text('before\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD').strip()
        (self.repo / 'target.txt').write_text('after\n')
        self.git('commit', '-qam', 'head')
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.git('remote', 'add', 'origin', str(self.repo))
        fakebin = self.root / 'bin'
        fakebin.mkdir()
        metadata = {'number': 50, 'headRefOid': self.head, 'baseRefOid': self.base}
        (fakebin / 'gh').write_text('#!' + sys.executable + '\n'
            'import json\nprint(' + repr(json.dumps(metadata)) + ')\n')
        executable = '''import hashlib,json,os,sys
from pathlib import Path
raw=sys.stdin.buffer.read()
Path(os.environ['TEST_LOG']).write_text(json.dumps({
    'sha256':hashlib.sha256(raw).hexdigest(), 'size':len(raw),
    'argv':sys.argv[1:], 'review_env':[k for k in os.environ if k.startswith('REVIEW_')]}))
if os.environ.get('TEST_EXIT'):
    sys.exit(int(os.environ['TEST_EXIT']))
for row in [
    {'type':'item.completed','item':{'type':'command_execution','command':'git diff'}},
    {'type':'item.completed','item':{'type':'agent_message','text':'Target inspected.'}},
    {'type':'turn.completed'}]:
    print(json.dumps(row))
'''
        for name in ('codex', 'claude'):
            (fakebin / name).write_text('#!' + sys.executable + '\n' + executable)
        for path in fakebin.iterdir():
            path.chmod(0o755)
        lessons = self.root / 'lessons'
        lessons.mkdir()
        for number in range(3):
            directory = lessons / str(number)
            directory.mkdir()
            (directory / 'LEAD.md').write_text(chr(65 + number) * 100000)
        self.env = dict(self.clean, PATH=str(fakebin) + os.pathsep + self.clean['PATH'],
                        REVIEW_ARTIFACTS=str(self.root / 'artifacts'),
                        REVIEW_LESSONS=str(lessons), TEST_LOG=str(self.root / 'seen.json'),
                        PYTHONDONTWRITEBYTECODE='1')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args],
                                       env=self.clean, text=True)

    def review(self, executor, number, env=None):
        data = json.dumps({'number': number, 'headRefOid': self.head, 'baseRefOid': self.base})
        binpath = Path(self.env['PATH'].split(os.pathsep)[0]) / 'gh'
        binpath.write_text('#!' + sys.executable + '\nimport json\nprint(' + repr(data) + ')\n')
        return subprocess.run([str(SCRIPTS / 'review-pr.sh'), str(self.repo), str(number), 'auto', executor],
                              env=self.env if env is None else env, capture_output=True)

    def test_long_prompt_arrives_once_with_eof(self):
        for number, executor in ((50, 'codex'), (51, 'claude')):
            with self.subTest(executor=executor):
                result = self.review(executor, number)
                self.assertEqual(result.returncode, 10, result.stderr.decode(errors='replace')[-500:])
                prompt = next((self.root / 'artifacts').rglob(f'{number}/round-0001/prompt.txt'))
                frozen = prompt.read_bytes()
                seen = json.loads(Path(self.env['TEST_LOG']).read_text())
                self.assertGreater(len(frozen), 262144)
                self.assertEqual(seen['sha256'], hashlib.sha256(frozen).hexdigest())
                self.assertEqual(seen['size'], len(frozen))
                self.assertEqual(seen['review_env'], [])
                self.assertTrue(all(len(arg) < 1000 for arg in seen['argv']))
                if executor == 'codex':
                    self.assertEqual(seen['argv'], ['exec', '--json', '-s', 'read-only', '-'])
                else:
                    self.assertEqual(seen['argv'], ['-p', '--input-format', 'text',
                                                    '--output-format', 'stream-json', '--verbose'])

    def test_failed_child_keeps_one_attempt_and_raw_exit(self):
        result = self.review('codex', 52, dict(self.env, TEST_EXIT='42'))
        self.assertEqual(result.returncode, 5)
        root = next((self.root / 'artifacts').rglob('52/round-0001/executor-exit.txt'))
        self.assertEqual(root.read_text(), '42')
        self.assertEqual(len(list((root.parent.parent).glob('round-*'))), 1)


if __name__ == '__main__':
    unittest.main()
