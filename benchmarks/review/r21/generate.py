#!/usr/bin/env python3
"""Generate eight offline review cases; keep the oracle outside reviewer bundles."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def case(identifier, kind, requirement, base, head, witness, repair=None, unavailable=None):
    return dict(id=identifier, kind=kind, requirement=requirement, base=base, head=head,
                repair=repair, witness=witness, unavailable=unavailable or [])


CASES = [
    case('case-01', 'normal', 'A missing user must be rejected by the existing validator.\n',
         {'app.py': 'def validate(user):\n    if user is None: raise ValueError("missing")\n'
                    'def submit(user):\n    validate(user)\n    return "ok"\n'},
         {'app.py': 'def validate(user):\n    if user is None: raise ValueError("missing")\n'
                    'def submit(user):\n    validate(user)\n    return "accepted"\n'},
         'import app\ntry: app.submit(None)\nexcept ValueError: pass\nelse: raise AssertionError("missing user accepted")\n'),
    case('case-02', 'defect-repair', 'A round trip must return the original integer type and value.\n',
         {'app.py': 'def write(n): return str(n)\ndef read(raw): return int(raw)\n'},
         {'app.py': 'def write(n): return str(n)\ndef read(raw): return raw\n'},
         'import app\nassert app.read(app.write(7)) == 7\nassert type(app.read(app.write(7))) is int\n',
         {'app.py': 'def write(n): return str(n)\ndef read(raw): return int(raw)\n'}),
    case('case-03', 'defect-repair', 'Nonpositive amounts must be rejected.\n',
         {'app.py': 'def submit(amount):\n    if amount <= 0: raise ValueError("amount")\n    return amount\n'},
         {'app.py': 'def submit(amount):\n    return amount\n'},
         'import app\ntry: app.submit(0)\nexcept ValueError: pass\nelse: raise AssertionError("validation missing")\n',
         {'app.py': 'def submit(amount):\n    if amount <= 0: raise ValueError("amount")\n    return amount\n'}),
    case('case-04', 'defect-repair', 'The runtime policy must deny guest access.\n',
         {'app.py': 'from pathlib import Path\ndef guest_allowed():\n'
                    '    return "allow_guest=true" in Path(__file__).with_name("runtime.md").read_text()\n',
          'runtime.md': 'allow_guest=false\n'},
         {'app.py': 'from pathlib import Path\ndef guest_allowed():\n'
                    '    return "allow_guest=true" in Path(__file__).with_name("runtime.md").read_text()\n',
          'runtime.md': 'allow_guest=true\n'},
         'import app\nassert app.guest_allowed() is False\n',
         {'app.py': 'from pathlib import Path\ndef guest_allowed():\n'
                    '    return "allow_guest=true" in Path(__file__).with_name("runtime.md").read_text()\n',
          'runtime.md': 'allow_guest=false\n'}),
    case('case-05', 'defect-repair', 'The safe and unsafe branches must return distinct signed values.\n',
         {'app.py': 'def token(kind):\n    if kind == "safe": return "+value"\n'
                    '    if kind == "unsafe": return "-value"\n    raise ValueError(kind)\n'},
         {'app.py': 'def token(kind):\n    if kind == "safe": return "+value"\n'
                    '    if kind == "unsafe": return "+value"\n    raise ValueError(kind)\n'},
         'import app\nassert app.token("safe") == "+value"\nassert app.token("unsafe") == "-value"\n',
         {'app.py': 'def token(kind):\n    if kind == "safe": return "+value"\n'
                    '    if kind == "unsafe": return "-value"\n    raise ValueError(kind)\n'}),
    case('case-06', 'repair-regression', 'The public caller must return a text ID.\n',
         {'app.py': 'def encode(value): return str(value)\ndef caller(value): return "ID:" + encode(value)\n'},
         {'app.py': 'def encode(value): return str(value).encode("utf-8")\n'
                    'def caller(value): return "ID:" + encode(value)\n'},
         'import app\nassert app.caller(7) == "ID:7"\n',
         {'app.py': 'def encode(value): return str(value)\ndef caller(value): return "ID:" + encode(value)\n'}),
    case('case-07', 'normal', 'Scaling remains correct; an unrelated stable module is unchanged.\n',
         {'helper.py': 'def scale(value):\n    return value * 2\n',
          'unrelated.py': 'def stable(): return 41\n'},
         {'helper.py': 'def scale(value):\n    doubled = value + value\n    return doubled\n',
          'unrelated.py': 'def stable(): return 41\n'},
         'import helper, unrelated\nassert helper.scale(3) == 6\nassert unrelated.stable() == 41\n'),
    case('case-08', 'known-blocker-and-gap',
         'Missing receipt must block publication. A separate platform-only check is required but unavailable here.\n',
         {'app.py': 'def publish(receipt): return bool(receipt)\n'},
         {'app.py': 'def publish(receipt): return True\n'},
         'import app\nassert app.publish(None) is False\nassert app.publish("proof") is True\n',
         {'app.py': 'def publish(receipt): return bool(receipt)\n'},
         unavailable=['platform-only witness: NOT_RUN']),
]

RUBRICS = {
    'case-01': 'Normal control: the existing validator rejects a missing user; do not invent a blocker.',
    'case-02': 'One type/consumer mismatch: read returns text rather than the required integer.',
    'case-03': 'The old validation was deleted; a nonpositive amount reaches submit.',
    'case-04': 'runtime.md is read by app.py; the changed policy enables forbidden guest access.',
    'case-05': 'The unsafe branch is the defective second return; the similar safe return is correct.',
    'case-06': 'The changed encoder returns bytes and breaks its unchanged text caller.',
    'case-07': 'Normal local refactor; unrelated.py is unchanged and no broad redesign is warranted.',
    'case-08': 'Missing receipt is a known blocker; platform-only evidence remains NOT_RUN.',
}


def git(repo, *args, env=None, capture=True):
    command = ['git', '-C', str(repo), *args]
    result = subprocess.run(command, env=env, capture_output=True, check=True)
    return result.stdout.strip() if capture else b''


def install(repo, files):
    old = {name.decode() for name in git(repo, 'ls-files', '-z').split(b'\0') if name}
    for name in old - files.keys():
        (repo / name).unlink()
    for name, body in files.items():
        (repo / name).write_text(body, encoding='utf-8')


def generate(reviewer_dir, oracle_dir):
    reviewer_dir, oracle_dir = Path(reviewer_dir).resolve(), Path(oracle_dir).resolve()
    if reviewer_dir == oracle_dir or reviewer_dir.is_relative_to(oracle_dir) or oracle_dir.is_relative_to(reviewer_dir):
        raise ValueError('reviewer and oracle directories must be separate')
    if reviewer_dir.exists() or oracle_dir.exists():
        raise FileExistsError('refusing to overwrite an existing output directory')
    reviewer_dir.mkdir(parents=True)
    oracle_dir.mkdir(parents=True)
    clean = {key: value for key, value in os.environ.items() if not key.startswith(('GIT_', 'REVIEW_'))}
    clean.update(GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid',
                 GIT_COMMITTER_NAME='Fixture', GIT_COMMITTER_EMAIL='fixture@example.invalid',
                 GIT_AUTHOR_DATE='2000-01-01T00:00:00 +0000',
                 GIT_COMMITTER_DATE='2000-01-01T00:00:00 +0000')
    manifest = []
    with tempfile.TemporaryDirectory(prefix='review-r21-cases-') as temporary:
        for item in CASES:
            repo = Path(temporary) / item['id']
            subprocess.run(['git', 'init', '-q', '-b', 'main', str(repo)], env=clean, check=True)
            git(repo, 'config', 'commit.gpgsign', 'false', env=clean)
            git(repo, 'config', 'core.autocrlf', 'false', env=clean)
            versions = {}
            for index, label in enumerate(('base', 'head', 'repair')):
                if item[label] is None:
                    continue
                files = dict(item[label], **{'requirements.md': item['requirement']})
                install(repo, files)
                git(repo, 'add', '-A', env=clean)
                dated = dict(clean, GIT_AUTHOR_DATE=f'2000-01-0{index + 1}T00:00:00 +0000',
                             GIT_COMMITTER_DATE=f'2000-01-0{index + 1}T00:00:00 +0000')
                git(repo, 'commit', '-qm', item['id'] + '-' + label, env=dated)
                versions[label] = git(repo, 'rev-parse', 'HEAD', env=clean).decode()
            git(repo, 'branch', 'review-head', versions['head'], env=clean)
            bundle = reviewer_dir / (item['id'] + '.bundle')
            git(repo, 'bundle', 'create', str(bundle), 'refs/heads/review-head', env=clean)
            repair_bundle = None
            if 'repair' in versions:
                repair_bundle = oracle_dir / (item['id'] + '-repair.bundle')
                git(repo, 'bundle', 'create', str(repair_bundle), 'refs/heads/main', env=clean)
            manifest.append({'id': item['id'], 'bundle': bundle.name,
                             'versions': {key: versions[key] for key in ('base', 'head')},
                             'quality_comparison': 'NOT_RUN'})
            expected = {'base': 'PASS', 'head': 'PASS' if item['kind'] == 'normal' else 'FAIL'}
            if item['repair'] is not None:
                expected['repair'] = 'PASS'
            (oracle_dir / (item['id'] + '.json')).write_text(json.dumps({
                'id': item['id'], 'kind': item['kind'], 'marker': 'PRIVATE_RUBRIC_ONLY',
                'witness': item['witness'], 'repair_sha': versions.get('repair'),
                'repair_bundle': repair_bundle.name if repair_bundle else None,
                'expected': expected, 'unavailable': item['unavailable'],
                'rubric': RUBRICS[item['id']]},
                sort_keys=True, indent=2) + '\n', encoding='utf-8')
    (reviewer_dir / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2) + '\n',
                                                encoding='utf-8')
    return manifest


def selftest():
    with tempfile.TemporaryDirectory(prefix='review-r21-selftest-') as temporary:
        root = Path(temporary)
        first = generate(root / 'first-reviewer', root / 'first-oracle')
        second = generate(root / 'second-reviewer', root / 'second-oracle')
        assert first == second and len(first) == 8
        for entry in first:
            oracle = json.loads((root / 'first-oracle' / (entry['id'] + '.json')).read_text())
            assert 'PRIVATE_RUBRIC_ONLY' not in (root / 'first-reviewer/manifest.json').read_text()
            checkout = root / ('checkout-' + entry['id'])
            subprocess.run(['git', 'clone', '-q', '-b', 'review-head',
                            str(root / 'first-reviewer' / entry['bundle']),
                            str(checkout)], check=True)
            if oracle['repair_sha']:
                missing_repair = subprocess.run(['git', '-C', str(checkout), 'cat-file', '-e',
                                                 oracle['repair_sha'] + '^{commit}'],
                                                capture_output=True)
                assert missing_repair.returncode != 0, 'repair leaked into reviewer Git history'
            for label, sha in entry['versions'].items():
                git(checkout, 'checkout', '--quiet', '--detach', sha)
                names = git(checkout, 'ls-tree', '-r', '--name-only', sha).decode().splitlines()
                assert names and not any('oracle' in name or 'rubric' in name for name in names)
                for name in names:
                    assert 'PRIVATE_RUBRIC_ONLY' not in git(checkout, 'show', sha + ':' + name).decode()
                result = subprocess.run([sys.executable, '-c', oracle['witness']], cwd=checkout,
                                        capture_output=True,
                                        env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
                actual = 'PASS' if result.returncode == 0 else 'FAIL'
                assert actual == oracle['expected'][label], (entry['id'], label, actual)
            if oracle['repair_sha']:
                private_checkout = root / ('private-checkout-' + entry['id'])
                subprocess.run(['git', 'clone', '-q',
                                str(root / 'first-oracle' / oracle['repair_bundle']),
                                str(private_checkout)], check=True)
                git(private_checkout, 'checkout', '--quiet', '--detach', oracle['repair_sha'])
                repaired = subprocess.run([sys.executable, '-c', oracle['witness']],
                                          cwd=private_checkout, capture_output=True,
                                          env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
                assert repaired.returncode == 0 and oracle['expected']['repair'] == 'PASS'
            if entry['id'] == 'case-08':
                assert oracle['unavailable'] == ['platform-only witness: NOT_RUN']
            print('ok   ' + entry['id'] + ' (' + oracle['kind'] + ')')
        assert all(entry['quality_comparison'] == 'NOT_RUN' for entry in first)


if __name__ == '__main__':
    if sys.argv[1:] == ['--selftest']:
        selftest()
    elif len(sys.argv) == 3:
        generate(sys.argv[1], sys.argv[2])
    else:
        sys.exit('usage: generate.py --selftest | generate.py REVIEWER_DIR ORACLE_DIR')
