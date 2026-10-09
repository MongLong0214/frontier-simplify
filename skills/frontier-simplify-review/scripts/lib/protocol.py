"""Git identities and byte integrity; review prose is not an authorization language."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

class Rejected(Exception):
    pass


def require(condition, tag, reason):
    if not condition:
        raise Rejected(f'GUARD FAIL [{tag}] {reason}')


def child_environment():
    routing = {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_PREFIX', 'GIT_COMMON_DIR',
               'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES'}
    return {key: value for key, value in os.environ.items()
            if key not in routing and (not key.startswith('REVIEW_') or key.startswith('REVIEW_TEST_'))}


def git(repo, *args, literal=False):
    env = child_environment()
    options = []
    if literal:
        for key in ('GIT_LITERAL_PATHSPECS', 'GIT_GLOB_PATHSPECS',
                    'GIT_NOGLOB_PATHSPECS', 'GIT_ICASE_PATHSPECS'):
            env.pop(key, None)
        options.append('--literal-pathspecs')
    return subprocess.check_output(['git', *options, '-C', str(repo), *args],
                                   env=env, stderr=subprocess.PIPE)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def artifact_root():
    # Keep legacy paths in place: mirror paths participate in PR identity. Moving them
    # would hide existing receipts and reset the same PR's automatic attempt budget.
    legacy = Path.home() / '.sol-simplify-review'
    default = legacy if legacy.exists() else Path.home() / '.frontier-simplify-review'
    return Path(os.environ.get('REVIEW_ARTIFACTS', str(default))).resolve()


def protocol_sha256(scripts):
    """Fingerprint of everything that decides a round's outcome.

    SKILL.md alone is not the protocol. The guards live under scripts/, and a correction there
    changes what a round is judged by while leaving the prose byte-identical -- measured: eight
    guard fixes moved no SKILL.md byte, so every receipt still claimed the same version and audit
    read the corrections as forgeries. A version that does not cover the code it versions cannot
    tell an upgrade from tampering, which is the only question it is asked.
    """
    parts = [(scripts.parent / 'SKILL.md').read_bytes()]
    for path in sorted(p for p in scripts.rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts):
        parts.append(str(path.relative_to(scripts)).encode() + b'\0' + path.read_bytes())
    return digest(b'\0'.join(parts))


def review_context(scripts, executor, response, redesign=None):
    """Caller-selected inputs; generated PR history must not invalidate its own review."""
    values = {key: os.environ.get(key, default) for key, default in {
        'REVIEW_REQUIREMENTS': 'none', 'REVIEW_ROUTED': 'none', 'REVIEW_CATALOG': 'none',
        'REVIEW_SUITE_STATUS': 'UNKNOWN', 'REVIEW_TOOL_NOTES': 'none',
        'REVIEW_CODEX_MODEL': '', 'REVIEW_TARGET_OID': '', 'REVIEW_TIMEOUT': '1800',
        'REVIEW_WITNESS_DISPUTED': '', 'REVIEW_WITNESS_WRAPPER': '',
    }.items()}
    context = dict(inputs_sha256=digest(json.dumps(values, sort_keys=True).encode()),
                   response_sha256=digest(response) if response is not None else None,
                   protocol_sha256=protocol_sha256(scripts), executor=executor,
                   model=os.environ.get('REVIEW_CODEX_MODEL') or 'executor default',
                   model_revision='unknown')
    if redesign is not None:
        context['redesign_sha256'] = digest(redesign)
    return context



def changed(repo, base, head):
    raw = git(repo, 'diff', '--no-renames', '--name-only', '-z', base, head, literal=True)
    paths = [p.decode('utf-8') for p in raw.split(b'\0') if p]
    require(all('\r' not in p and '\n' not in p for p in paths),
            'target-path', 'newline filenames cannot be represented in the line-based target inventory')
    return paths


def hunks(repo, base, head):
    """Zero-context git hunks, plus one unit for a file with only binary/mode/empty changes.

    Disable rename detection: both rename endpoints are accounted, including rename+edit.
    File metadata is included in the first hunk's identity, never silently dropped.
    """
    result = []
    for path in changed(repo, base, head):
        patch = git(repo, 'diff', '--no-color', '--no-ext-diff', '--no-textconv', '--no-renames',
                    '--binary', '--unified=0', base, head, '--', path, literal=True)
        starts = [m.start() for m in re.finditer(rb'^@@ ', patch, re.M)]
        parts = []
        if starts:
            for i, start in enumerate(starts):
                end = starts[i + 1] if i + 1 < len(starts) else len(patch)
                unit = patch[start:end]
                label = unit.split(b'\n', 1)[0].decode('utf-8', 'replace')
                parts.append((label, (patch[:start] if i == 0 else b'') + unit))
        else:
            parts.append(('whole-file (binary, mode, or empty-file change)', patch))
        for label, unit in parts:
            identity = b'\0'.join([base.encode(), head.encode(), path.encode(), unit])
            result.append({'id': 'H-' + digest(identity)[:20], 'path': path, 'hunk': label})
    require(len({h['id'] for h in result}) == len(result), 'hunk-identity', 'duplicate hunk identity')
    return result


def hunk_markdown(rows):
    return '\n'.join(f"- {r['id']} {json.dumps(r['path'], ensure_ascii=False)} {r['hunk']}" for r in rows) + '\n'


# Deliberately distinct from shell success: a recorded review is never a merge approval.
RECORDED = 10
FAILED = 5
HANDOFF = 11
# Returned before any reservation or model launch; neither consumes an attempt.
REDESIGN_REQUIRED = 12
WITNESS_FAILING = 13
MAX_ROUNDS = 3


def review_exit(recorded, attempts=0, limit=MAX_ROUNDS):
    if not recorded:
        return FAILED
    return HANDOFF if attempts >= limit else RECORDED
