"""Deterministic file metadata for one exact Git commit pair."""
import json
import re
import subprocess

from protocol import git, require, Rejected


def _git(repo, *args):
    try:
        return git(repo, *args)
    except (OSError, subprocess.CalledProcessError) as error:
        raise Rejected(f'GUARD FAIL [scope-git] Git query failed: {type(error).__name__}') from error


def _path(raw):
    require(bool(raw), 'unsupported-path', 'empty Git path')
    try:
        decoded = raw.decode('utf-8', 'strict')
    except UnicodeDecodeError as error:
        raise Rejected('GUARD FAIL [unsupported-path] Git path is not UTF-8') from error
    require('\r' not in decoded and '\n' not in decoded, 'unsupported-path',
            'CR/LF Git paths are not supported by the target inventory')
    return decoded


def _records(raw, label):
    if not raw:
        return []
    require(raw.endswith(b'\0'), 'scope-format', f'truncated {label} record')
    return raw[:-1].split(b'\0')


def _raw_files(data, oid_length):
    fields = _records(data, 'raw')
    require(len(fields) % 2 == 0, 'scope-format', 'truncated raw file entry')
    result = {}
    for offset in range(0, len(fields), 2):
        header, raw_path = fields[offset:offset + 2]
        require(header.startswith(b':'), 'scope-format', 'raw entry has no mode header')
        columns = header[1:].split(b' ')
        require(len(columns) == 5, 'scope-format', 'raw entry has missing fields')
        old_mode, new_mode, old_oid, new_oid, status = columns
        require(all(re.fullmatch(rb'[0-7]{6}', mode) for mode in (old_mode, new_mode)),
                'scope-format', 'raw entry has invalid mode')
        require(all(re.fullmatch(rb'[0-9a-f]{' + str(oid_length).encode() + rb'}', oid)
                    for oid in (old_oid, new_oid)), 'scope-format', 'raw entry has non-full object ID')
        require(status in {b'A', b'M', b'D', b'T'}, 'scope-format', 'unsupported raw change status')
        require((old_mode == b'000000') == (old_oid == b'0' * oid_length) and
                (new_mode == b'000000') == (new_oid == b'0' * oid_length),
                'scope-format', 'raw mode and object presence disagree')
        path = _path(raw_path)
        require(raw_path not in result, 'scope-format', 'duplicate raw path')
        result[raw_path] = {'path': path, 'status': status.decode(),
                            'old': None if old_mode == b'000000' else
                            {'mode': old_mode.decode(), 'oid': old_oid.decode()},
                            'new': None if new_mode == b'000000' else
                            {'mode': new_mode.decode(), 'oid': new_oid.decode()}}
    return result


def _numstat(data):
    result = {}
    for record in _records(data, 'numstat'):
        columns = record.split(b'\t', 2)
        require(len(columns) == 3, 'scope-format', 'truncated numstat entry')
        added, deleted, raw_path = columns
        _path(raw_path)
        require(raw_path not in result, 'scope-format', 'duplicate numstat path')
        if added == deleted == b'-':
            result[raw_path] = (True, None, None)
        else:
            require(re.fullmatch(rb'[0-9]+', added) and re.fullmatch(rb'[0-9]+', deleted),
                    'scope-format', 'invalid numstat counts')
            result[raw_path] = (False, int(added), int(deleted))
    return result


def _regular(item):
    return item is None or item['mode'] in {'100644', '100755'}


def build_scope(repo, from_sha, to_sha, input_kind):
    require(input_kind in {'change', 'remediation'}, 'scope-kind', 'unknown scope input kind')
    require(all(isinstance(sha, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', sha)
                for sha in (from_sha, to_sha)) and len(from_sha) == len(to_sha),
            'scope-target', 'provide two full exact commit IDs')
    for sha in (from_sha, to_sha):
        actual = _git(repo, 'rev-parse', '--verify', sha + '^{commit}').decode().strip()
        require(actual == sha, 'scope-target', 'Git target is not the requested commit')
    scope = {'schema_version': 1, 'input_kind': input_kind,
             'from_sha': from_sha, 'to_sha': to_sha, 'files': [], 'groups': []}
    if from_sha == to_sha:
        return scope
    options = ('-z', '--no-renames', '--no-ext-diff', '--no-textconv')
    raw = _git(repo, 'diff', '--raw', '--abbrev=64', *options, from_sha, to_sha)
    stats = _git(repo, 'diff', '--numstat', *options, from_sha, to_sha)
    entries = _raw_files(raw, len(from_sha))
    counts = _numstat(stats)
    require(entries.keys() == counts.keys(), 'scope-format', 'raw and numstat file sets differ')
    for number, raw_path in enumerate(sorted(entries)):
        item = entries[raw_path]
        binary, insertions, deletions = counts[raw_path]
        if item['status'] == 'T' or not (_regular(item['old']) and _regular(item['new'])):
            binary = insertions = deletions = None
        item.update(id=f'f-{number}', is_binary=binary,
                    insertions=insertions, deletions=deletions)
        scope['files'].append(item)
        scope['groups'].append({'id': f'g-{number}', 'primary_file_ids': [item['id']],
                                'basis': 'singleton'})
    return scope


def scope_bytes(scope):
    return (json.dumps(scope, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':')) + '\n').encode('utf-8')
