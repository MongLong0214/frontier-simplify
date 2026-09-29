#!/usr/bin/env python3
"""Exact Git metadata and deterministic singleton scope fixtures."""
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'lib'))
from protocol import Rejected
from scope import _finalize_groups, _numstat, _path, _raw_files, build_scope, group_files, scope_bytes


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


def check(name, good):
    print(('ok   ' if good else 'NOT OK ') + name)
    return good


with tempfile.TemporaryDirectory(prefix='review-scope-test-') as temporary:
    repo = Path(temporary) / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.name', 'test')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    git(repo, 'config', 'core.filemode', 'true')
    (repo / 'initial.txt').write_text('seed\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'initial')
    seed = git(repo, 'rev-parse', 'HEAD')
    for name, body in [('modify.txt', 'before\n'), ('delete.txt', 'removed\n'),
                       ('mode.sh', 'same\n'), ('rename-old.txt', 'old name\n'),
                       ('type', None)]:
        path = repo / name
        if body is None:
            path.symlink_to('initial.txt')
        else:
            path.write_text(body)
    (repo / 'binary.bin').write_bytes(b'\0before')
    git(repo, 'add', '.')
    git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{seed},submodule')
    git(repo, 'commit', '-qm', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'modify.txt').write_text('after\n')
    (repo / 'delete.txt').unlink()
    (repo / 'mode.sh').chmod(0o755)
    git(repo, 'mv', 'rename-old.txt', 'rename-new.txt')
    (repo / 'rename-new.txt').write_text('renamed and edited\n')
    (repo / 'type').unlink()
    (repo / 'type').write_text('regular now\n')
    (repo / 'binary.bin').write_bytes(b'\0after')
    (repo / 'add.txt').write_text('new\n')
    (repo / 'empty.txt').touch()
    (repo / '한글 space:\t, name.txt').write_text('special\n')
    (repo / 'new-link').symlink_to('missing-target')
    git(repo, 'add', '-A')
    git(repo, 'update-index', '--add', '--cacheinfo', f'160000,{base},submodule')
    git(repo, 'commit', '-qm', 'head')
    head = git(repo, 'rev-parse', 'HEAD')
    results = []
    scope = build_scope(repo, base, head, 'change')
    encoded = scope_bytes(scope)
    paths = [p for p in subprocess.check_output(['git', '-C', str(repo), 'diff',
             '--no-renames', '--name-only', '-z', base, head]).split(b'\0') if p]
    files = scope['files']
    by_path = {item['path']: item for item in files}
    results.append(check('exact-raw-path-set-and-byte-order',
                         [item['path'].encode() for item in files] == sorted(paths)
                         and len(by_path) == len(paths)
                         and [item['id'] for item in files] ==
                         [f'f-{number}' for number in range(len(files))]))
    results.append(check('singleton-groups-partition-primary-files',
                         [group['primary_file_ids'] for group in scope['groups']] ==
                         [[item['id']] for item in files]
                         and [group['id'] for group in scope['groups']] ==
                         [f'g-{number}' for number in range(len(files))]
                         and all(group['basis'] == 'singleton' for group in scope['groups'])))
    results.append(check('schema-and-serialization-are-deterministic',
                         scope['schema_version'] == 1 and scope['input_kind'] == 'change'
                         and scope['from_sha'] == base and scope['to_sha'] == head
                         and encoded == scope_bytes(build_scope(repo, base, head, 'change'))
                         and encoded == (json.dumps(scope, sort_keys=True, ensure_ascii=False,
                                                    separators=(',', ':')) + '\n').encode('utf-8')))
    results.append(check('add-modify-delete-and-rename-endpoints',
                         by_path['add.txt']['status'] == 'A'
                         and by_path['add.txt']['old'] is None
                         and by_path['delete.txt']['status'] == 'D'
                         and by_path['delete.txt']['new'] is None
                         and by_path['modify.txt']['status'] == 'M'
                         and by_path['rename-old.txt']['status'] == 'D'
                         and by_path['rename-new.txt']['status'] == 'A'))
    results.append(check('mode-binary-empty-and-type-stats',
                         by_path['mode.sh']['status'] == 'M'
                         and by_path['mode.sh']['old']['mode'] == '100644'
                         and by_path['mode.sh']['new']['mode'] == '100755'
                         and (by_path['mode.sh']['insertions'], by_path['mode.sh']['deletions']) == (0, 0)
                         and by_path['empty.txt']['is_binary'] is False
                         and (by_path['empty.txt']['insertions'], by_path['empty.txt']['deletions']) == (0, 0)
                         and by_path['binary.bin']['is_binary'] is True
                         and by_path['binary.bin']['insertions'] is None
                         and by_path['type']['status'] == 'T'
                         and by_path['type']['is_binary'] is None
                         and by_path['new-link']['is_binary'] is None
                         and by_path['submodule']['is_binary'] is None
                         and by_path['submodule']['old']['oid'] == seed
                         and by_path['submodule']['new']['oid'] == base))
    results.append(check('special-utf8-path-preserved',
                         '한글 space:\t, name.txt' in by_path))
    remediation = build_scope(repo, base, head, 'remediation')
    results.append(check('remediation-kind-retains-the-exact-pair',
                         remediation['input_kind'] == 'remediation'
                         and remediation['files'] == files))
    old_oid = by_path['modify.txt']['old']['oid'].encode()
    new_oid = by_path['modify.txt']['new']['oid'].encode()
    bad_header = b':100644 100644 ' + old_oid + b' ' + new_oid
    for label, fn in [('unknown-status', lambda: _raw_files(bad_header + b' X\0bad\0', len(head))),
                      ('truncated-raw', lambda: _raw_files(bad_header + b' M\0bad', len(head))),
                      ('truncated-numstat', lambda: _numstat(b'1\t0\tbad'))]:
        try:
            fn()
        except Rejected as error:
            rejected = '[scope-format]' in str(error)
        else:
            rejected = False
        results.append(check(label + '-is-not-empty-success', rejected))
    empty = build_scope(repo, head, head, 'remediation')
    results.append(check('valid-same-sha-is-empty-not-error',
                         empty['files'] == [] and empty['groups'] == []))
    (repo / 'initial.txt').write_text('branch moved\n')
    git(repo, 'commit', '-qam', 'move branch')
    results.append(check('resolved-sha-pair-ignores-later-branch-move',
                         scope_bytes(build_scope(repo, base, head, 'change')) == encoded))
    for label, name in [('cr', b'bad\rname'), ('lf', b'bad\nname'),
                        ('invalid-utf8', b'bad\xffname')]:
        raw = os.fsencode(repo) + b'/' + name
        try:
            fd = os.open(raw, os.O_CREAT | os.O_WRONLY, 0o644)
        except OSError as error:
            if label == 'invalid-utf8' and error.errno == errno.EILSEQ:
                try:
                    _path(name)
                except Rejected as rejected_error:
                    rejected = '[unsupported-path]' in str(rejected_error)
                else:
                    rejected = False
                results.append(check('invalid-utf8-parser-refusal', rejected))
                print('skip invalid-utf8-Git-path: filesystem rejects this byte name')
                continue
            raise
        os.write(fd, b'bad\n')
        os.close(fd)
        prior = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', label)
        current = git(repo, 'rev-parse', 'HEAD')
        try:
            build_scope(repo, prior, current, 'change')
        except Rejected as error:
            rejected = '[unsupported-path]' in str(error)
        else:
            rejected = False
        results.append(check(label + '-is-explicitly-unsupported', rejected))
    try:
        build_scope(repo, 'f' * len(head), head, 'change')
    except Rejected:
        missing_rejected = True
    else:
        missing_rejected = False
    results.append(check('missing-commit-is-not-empty-success', missing_rejected))

def sample(number, path, status='M', binary=False, mode='100644'):
    return {'id': f'f-{number}', 'path': path, 'status': status,
            'old': {'mode': mode}, 'new': {'mode': mode}, 'is_binary': binary}


group_results = []
group_results.append(check('empty-and-singleton-grouping',
                           group_files([]) == [] and group_files([sample(0, 'solo.py')]) ==
                           [{'id': 'g-0', 'primary_file_ids': ['f-0'], 'basis': 'singleton'}]))
paired = [sample(10, 'pkg/한글,part:two.test.py'),
          sample(2, 'pkg/한글,part:two.py'),
          sample(11, 'pkg/한글,part:two.spec.py'),
          sample(3, 'other/한글,part:two.test.py'),
          sample(4, 'pkg/한글,part:two.test.ts'),
          sample(5, 'pkg/한글,part:two.ts')]
expected = [(['f-2', 'f-10', 'f-11'], 'implementation-test'),
            (['f-3'], 'singleton'), (['f-4', 'f-5'], 'implementation-test')]
groups = group_files(paired)
group_results.append(check('clear-pairs-only-and-numeric-order',
                           [(g['primary_file_ids'], g['basis']) for g in groups] == expected
                           and [g['id'] for g in groups] == ['g-0', 'g-1', 'g-2']))
group_results.append(check('group-order-independent-of-input-order',
                           groups == group_files(list(reversed(paired)))))
ambiguous = [sample(0, 'pkg/a.py'), sample(1, 'pkg/a.test.py', 'D'),
             sample(2, 'pkg/b.py'), sample(3, 'pkg/b.test.py', binary=True),
             sample(4, 'pkg/c.py'), sample(5, 'pkg/c.test.py', mode='120000'),
             sample(6, 'pkg/d.py'), sample(7, 'pkg/d.test.py', status='T'),
             sample(8, 'pkg/e.py'), sample(9, 'pkg/e.test.py', mode='160000')]
group_results.append(check('ineligible-files-remain-singletons',
                           all(g['basis'] == 'singleton' for g in group_files(ambiguous))))
missing, missing_error = _finalize_groups(paired[:2], [(['f-2'], 'singleton')])
group_results.append(check('missing-assignment-recovers-singleton',
                           missing_error is None and
                           {f for g in missing for f in g['primary_file_ids']} == {'f-2', 'f-10'}))
for label, bad in [('duplicate', [(['f-2', 'f-10'], 'implementation-test'),
                                   (['f-10'], 'singleton')]),
                   ('unknown', [(['f-2', 'f-999'], 'implementation-test')])]:
    fallback, diagnostic = _finalize_groups(paired[:2], bad)
    group_results.append(check(label + '-assignment-falls-back-to-all-singletons',
                               diagnostic and len(fallback) == 2 and
                               all(g['basis'] == 'singleton' for g in fallback)))

sys.exit(0 if all(results + group_results) else 1)
