#!/usr/bin/env python3
"""Actual review wrapper installs exact, immutable phase-specific scope input."""
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
from protocol import Rejected, digest


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def check(label, good):
    print(('ok   ' if good else 'NOT OK ') + label)
    return good


with tempfile.TemporaryDirectory(prefix='review-scope-runner-') as temporary:
    t = Path(temporary)
    repo = t / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    (repo / 'foo.py').write_text('before\n')
    (repo / 'foo.test.py').write_text('before test\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'foo.py').write_text('reviewed\n')
    (repo / 'foo.test.py').write_text('reviewed test\n')
    git(repo, 'commit', '-qam', 'reviewed')
    head = git(repo, 'rev-parse', 'HEAD')
    binpath = t / 'bin'
    binpath.mkdir()
    fake = binpath / 'codex'
    fake.write_text('#!' + sys.executable + '\n' + '''
import json, os, subprocess, sys
from pathlib import Path
scope_bytes = Path('SCOPE.json').read_bytes()
scope = json.loads(scope_bytes)
names = set(subprocess.check_output(['git', 'diff', '--no-renames', '--name-only',
                                     '-z', scope['from_sha'], scope['to_sha']]).decode().strip('\\0').split('\\0'))
assert scope['from_sha'] == os.environ['TEST_FROM']
assert scope['to_sha'] == os.environ['TEST_TO']
assert scope['input_kind'] == os.environ['TEST_KIND']
assert {item['path'] for item in scope['files']} == (names if names != {''} else set())
assert 'DIFF.patch' in os.listdir('.') and 'CHANGED.txt' in os.listdir('.')
if scope['input_kind'] == 'remediation':
    assert all(Path(name).exists() for name in ('ROUND1_INVENTORY.md', 'PREVIOUS_REVIEW.md',
        'IMPLEMENTER_RESPONSE.md', 'REMEDIATION.patch', 'REMEDIATION_CHANGED.txt',
        'REMEDIATION_HUNKS.md'))
Path(os.environ['TEST_LOG']).write_text(json.dumps({'scope': scope, 'scope_bytes': scope_bytes.decode(),
    'remediation_patch': Path('REMEDIATION.patch').read_text() if scope['input_kind'] == 'remediation' else None,
    'prompt': sys.stdin.buffer.read().decode()}))
if os.environ.get('TEST_TAMPER'):
    Path('SCOPE.json').write_text('tampered')
for row in [
    {'type':'item.completed','item':{'type':'command_execution','command':'cat SCOPE.json'}},
    {'type':'item.completed','item':{'type':'agent_message','text':'Reviewed frozen scope.'}},
    {'type':'turn.completed'}]:
    print(json.dumps(row))
''')
    fake.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith('REVIEW_')}
    env.update(PATH=str(binpath) + os.pathsep + env['PATH'],
               REVIEW_ARTIFACTS=str(t / 'artifacts'), PYTHONDONTWRITEBYTECODE='1')

    def host(pr, phase, to_sha, from_sha, kind, response=None, tamper=False):
        log = t / (pr + '-' + phase + '.json')
        local = dict(env, TEST_FROM=from_sha, TEST_TO=to_sha, TEST_KIND=kind,
                     TEST_LOG=str(log))
        if response:
            local['REVIEW_RESPONSE'] = str(response)
        if tamper:
            local['TEST_TAMPER'] = '1'
        result = subprocess.run([str(SCRIPTS / 'review-round.sh'), phase, str(repo), to_sha,
                                 pr, base, 'codex'], env=local, capture_output=True, text=True)
        return result, log

    def root(pr):
        return next((t / 'artifacts').glob('*/' + pr))

    results = []
    first, log = host('phase-one', '1', head, base, 'change')
    results.append(check('phase1-fake-executor-read-exact-frozen-scope',
                         first.returncode == 10 and log.exists() and
                         set(json.loads(log.read_text())['scope']['files'][n]['path'] for n in (0, 1)) ==
                         {'foo.py', 'foo.test.py'}))
    if first.returncode == 10:
        starts, ends, _ = ledger.audit(root('phase-one'), repo)
        data = json.loads(log.read_text())
        results.append(check('phase1-started-prepared-copy-and-prompt-agree',
                             starts[1].get('scope_schema_version') == 1 and
                             ledger.hashes(root('phase-one') / 'round-0001', ['SCOPE.json'])['SCOPE.json'] ==
                             starts[1]['inputs']['SCOPE.json'] and ends[1]['recorded'] and
                             ends[1]['checkout_observations']['input_copies']['status'] == 'unchanged' and
                             'SCOPE.json' in data['prompt']))
        legacy = dict(starts[1], inputs=dict(starts[1]['inputs']))
        legacy.pop('scope_schema_version')
        legacy['inputs'].pop('SCOPE.json')
        old_checks = ledger.recompute(repo, root('phase-one') / 'round-0001', legacy)
        missing = dict(starts[1], inputs=dict(starts[1]['inputs']))
        missing['inputs'].pop('SCOPE.json')
        missing_checks = ledger.recompute(repo, root('phase-one') / 'round-0001', missing)
        results.append(check('undeclared-legacy-is-readable-but-declared-missing-is-not',
                             next(c for c in old_checks if c['guard'] == 'input-digests')['ok'] and
                             not next(c for c in missing_checks if c['guard'] == 'input-digests')['ok']))
        def copied_history(name, transform):
            copy = t / name
            shutil.copytree(root('phase-one'), copy)
            rows = ledger.read(copy)
            transform(rows)
            (copy / 'ledger.jsonl').unlink()
            for row in rows:
                ledger.append(copy, row)
            return copy
        historic = copied_history('initial-v3-no-declaration', lambda rows: (
            rows[0].pop('scope_schema_version'), rows[1]['inputs'].pop('SCOPE.json')))
        results.append(check('initial-v3-without-declaration-remains-readable',
                             bool(ledger.audit(historic, repo)[2])))
        absent = copied_history('declared-prepared-missing', lambda rows: (
            rows[1]['inputs'].pop('SCOPE.json'), rows.pop()))
        try:
            ledger.audit(absent, repo)
        except Rejected as error:
            absent_refused = 'scope input digest' in str(error)
        else:
            absent_refused = False
        results.append(check('declared-prepared-missing-fails-even-before-execution', absent_refused))
        tampered = t / 'frozen-scope-tamper'
        shutil.copytree(root('phase-one'), tampered)
        (tampered / 'round-0001/SCOPE.json').write_text('{}')
        try:
            ledger.audit(tampered, repo)
        except Rejected:
            tamper_refused = True
        else:
            tamper_refused = False
        results.append(check('frozen-scope-hash-tamper-fails-readback', tamper_refused))
        malformed = t / 'scope-json-array'
        shutil.copytree(root('phase-one') / 'round-0001', malformed)
        (malformed / 'SCOPE.json').write_bytes(b'[]')
        malformed_start = dict(starts[1], inputs=dict(starts[1]['inputs']))
        malformed_start['inputs']['SCOPE.json'] = digest(b'[]')
        malformed_check = next(c for c in ledger.recompute(repo, malformed, malformed_start)
                               if c['guard'] == 'input-digests')
        results.append(check('rehashed-nonobject-scope-refused-without-reader-crash',
                             not malformed_check['ok'] and '[scope-target]' in malformed_check['reason']))
        for version in (0, 2):
            try:
                ledger.scope_version(dict(starts[1], scope_schema_version=version))
            except Rejected:
                refused = True
            else:
                refused = False
            results.append(check(f'unsupported-declared-version-{version}-refused', refused))
        (repo / 'foo.py').write_text('repaired\n')
        git(repo, 'commit', '-qam', 'repair')
        repaired = git(repo, 'rev-parse', 'HEAD')
        response = t / 'response.txt'
        response.write_text('Finding addressed with changed implementation.\n')
        followup, followup_log = host('phase-one', '2', repaired, head, 'remediation', response)
        followup_data = json.loads(followup_log.read_text()) if followup_log.exists() else {}
        results.append(check('phase2-reads-original-and-whole-remediation-scope',
                             followup.returncode == 10 and
                             followup_data.get('scope', {}).get('from_sha') == head and
                             followup_data.get('scope', {}).get('to_sha') == repaired and
                             'repaired' in followup_data.get('remediation_patch', '') and
                             'SCOPE.json' in followup_data.get('prompt', '') and
                             (root('phase-one') / 'round-0002/PREVIOUS_REVIEW.md').read_bytes() ==
                             (root('phase-one') / 'round-0001/ARTIFACT.md').read_bytes() and
                             (root('phase-one') / 'round-0002/IMPLEMENTER_RESPONSE.md').read_bytes() ==
                             response.read_bytes()))
        phase_starts, _, _ = ledger.audit(root('phase-one'), repo)
        results.append(check('phase2-reserves-exact-original-and-previous-round',
                             phase_starts[2].get('original_round') == 1 and
                             phase_starts[2].get('previous_round') == 1))
        wrong_original = copied_history('wrong-original-round',
                                        lambda rows: rows[3].update(original_round=99))
        try:
            ledger.audit(wrong_original, repo)
        except Rejected as error:
            wrong_refused = 'original' in str(error)
        else:
            wrong_refused = False
        results.append(check('rehashed-original-round-substitution-refused', wrong_refused))
        old_phase2 = copied_history('older-phase2-without-original-round',
                                    lambda rows: rows[3].pop('original_round', None))
        results.append(check('older-phase2-binding-remains-readable',
                             bool(ledger.audit(old_phase2, repo)[2])))
        later_response = t / 'later-response.txt'
        later_response.write_text('Later evidence for the same repair.\n')
        third, _ = host('phase-one', '2', repaired, head, 'remediation', later_response)
        complete_starts, _, _ = ledger.audit(root('phase-one'), repo)
        results.append(check('third-attempt-binds-latest-usable-review',
                             third.returncode == 11 and complete_starts[3].get('previous_round') == 2))
        rebound = t / 'rebound-previous-review'
        shutil.copytree(root('phase-one'), rebound)
        stale_previous = (rebound / 'round-0001/ARTIFACT.md').read_bytes()
        (rebound / 'round-0003/PREVIOUS_REVIEW.md').write_bytes(stale_previous)
        rows = ledger.read(rebound)
        rows[6]['previous_round'] = 1
        rows[7]['inputs']['PREVIOUS_REVIEW.md'] = digest(stale_previous)
        (rebound / 'ledger.jsonl').unlink()
        for row in rows:
            ledger.append(rebound, row)
        try:
            ledger.audit(rebound, repo)
        except Rejected as error:
            rebound_refused = 'previous' in str(error)
        else:
            rebound_refused = False
        results.append(check('rehashed-older-previous-review-substitution-refused', rebound_refused))
        response_start, response_log = host('response-only', '1', head, base, 'change')
        response_followup, response_followup_log = host('response-only', 'auto', head, head,
                                                        'remediation', response)
        response_data = json.loads(response_followup_log.read_text()) if response_followup_log.exists() else {}
        response_rows = (root('response-only') / 'ledger.jsonl').read_bytes()
        if response_followup_log.exists():
            response_followup_log.unlink()
        response_cache, _ = host('response-only', 'auto', head, head, 'remediation', response)
        results.append(check('response-only-empty-remediation-keeps-review-and-cache',
                             response_start.returncode == 10 and response_followup.returncode == 10
                             and response_data.get('scope', {}).get('files') == []
                             and response_data.get('remediation_patch') == ''
                             and response_cache.returncode == 10
                             and (root('response-only') / 'ledger.jsonl').read_bytes() == response_rows
                             and not response_followup_log.exists()))
        empty, empty_log = host('empty-target', '1', base, base, 'change')
        results.append(check('empty-phase1-refused-before-executor',
                             empty.returncode == 5 and not empty_log.exists() and
                             not (root('empty-target') / 'ledger.jsonl').exists()))
        tamper, _ = host('copied-tamper', '1', head, base, 'change', tamper=True)
        tamper_end = ledger.read(root('copied-tamper'))[-1]
        results.append(check('copied-scope-tamper-is-observed-and-not-recorded',
                             tamper.returncode == 5 and not tamper_end.get('recorded') and
                             tamper_end.get('checkout_observations', {}).get('input_copies', {}).get('status') ==
                             'changed'))
    sys.exit(0 if all(results) else 1)
