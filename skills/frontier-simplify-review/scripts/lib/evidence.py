"""Reviewer witnesses outlive the checkout they were written in and run again without a model.

A reviewer's reproduction used to live in the disposable checkout and die with it, so the next
reviewer rebuilt it, and an unfinished repair cost a whole review to discover. One consumer
round reported "the same defect remains on the queue path" -- a fact the previous round's own
witness would have shown in seconds. The host keeps review_evidence/ outside the checkout and
reruns its witnesses on the next head first. A witness is a claim the reviewer wrote down as a
program; its exit code is the only thing read, and a pass is not closure by itself.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tempfile
import time

from protocol import digest, require, child_environment

EVIDENCE = 'review_evidence'
SKIP_DIRECTORIES = {'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
                    '.venv', 'venv', '.git'}
MAX_FILE, MAX_TOTAL, MAX_FILES = 1 << 20, 16 << 20, 200
WITNESS_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}')
OBSOLETE = re.compile(r'^[ \t]*[-*][ \t]+witness_obsolete:[ \t]*`?([A-Za-z0-9][A-Za-z0-9._-]*)`?'
                      r'[ \t]*(?:--|—|–|:|\|)?[ \t]*(.*?)[ \t]*$', re.M)


def run(args, cwd=None):
    return subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, env=child_environment())


def evidence_path(rel):
    path = PurePosixPath(rel)
    require(not path.is_absolute() and '..' not in path.parts and len(path.parts) >= 2
            and path.parts[0] == EVIDENCE and '\\' not in rel, 'witness-path',
            f'preserved witness path escapes {EVIDENCE}/: {rel!r}')
    return path


def prepare(clone, overlay):
    """Create review_evidence/ and restore earlier witnesses without replacing checkout files."""
    target = clone / EVIDENCE
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        return None, [f'{EVIDENCE} is not a directory in this tree; witnesses are not preserved']
    target.mkdir(exist_ok=True)
    installed, notes = {}, []
    for rel, source in sorted(overlay.items()):
        destination = clone / rel
        if destination.exists() or destination.is_symlink():
            notes.append(f'{rel} exists in this tree; the preserved copy was not installed')
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        destination.write_bytes(data)
        destination.chmod(source.stat().st_mode & 0o777)
        installed[rel] = digest(data)
    return installed, notes


def collect(clone, directory, installed):
    """Preserve files the reviewer created or changed under review_evidence/. Returns True if any."""
    base = clone / EVIDENCE
    if installed is None or base.is_symlink() or not base.is_dir():
        return False
    listed = run(['git', '--literal-pathspecs', '-C', clone, 'ls-files', '-z', '--', EVIDENCE])
    require(listed.returncode == 0, 'witness-collect', 'cannot list tracked evidence files')
    tracked = {p.decode('utf-8', 'surrogateescape') for p in listed.stdout.split(b'\0') if p}
    files, skipped, total = [], [], 0
    for current, directories, names in os.walk(base, followlinks=False):
        here = Path(current)
        for name in sorted(directories):
            if name in SKIP_DIRECTORIES or (here / name).is_symlink():
                skipped.append({'path': (here / name).relative_to(clone).as_posix() + '/',
                                'reason': 'dependency, cache or linked directory'})
        directories[:] = sorted(d for d in directories
                                if d not in SKIP_DIRECTORIES and not (here / d).is_symlink())
        for name in sorted(names):
            path = here / name
            rel = path.relative_to(clone).as_posix()
            if rel in tracked:
                continue
            if path.is_symlink() or not path.is_file() or '\n' in rel:
                skipped.append({'path': rel, 'reason': 'not a regular file'})
                continue
            size = path.stat().st_size
            if size > MAX_FILE or total + size > MAX_TOTAL or len(files) >= MAX_FILES:
                skipped.append({'path': rel, 'reason': 'over the preservation size or count limit'})
                continue
            data = path.read_bytes()
            if installed.get(rel) == digest(data):
                continue
            target = directory / 'witnesses' / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)
            total += len(data)
            files.append({'path': rel, 'sha256': digest(data), 'size': len(data)})
    if not files and not skipped:
        return False
    manifest = {'schema_version': 1, 'files': files, 'skipped': skipped}
    (directory / 'WITNESSES.json').write_bytes(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode() + b'\n')
    return True


def view(root, starts, ends, since):
    """Witnesses of the review sequence that began at attempt `since`, from recorded reviews.

    Later bytes replace earlier ones path by path. An ID is a top-level review_evidence/<ID>.sh.
    `- witness_obsolete: <ID> -- <reason>` in a later recorded review retires it; a retirement
    without a reason retires nothing.
    """
    witnesses, overlay = {}, {}
    for n in sorted(starts):
        end = ends.get(n, {})
        if n < since or not (end.get('executed') and end.get('recorded', end.get('accepted'))):
            continue
        directory = root / f'round-{n:04}'
        if 'WITNESSES.json' in end.get('outputs', {}):
            manifest = json.loads((directory / 'WITNESSES.json').read_bytes())
            require(manifest.get('schema_version') == 1 and isinstance(manifest.get('files'), list),
                    'witness-manifest', f'attempt {n} has an unknown witness manifest')
            for item in manifest['files']:
                rel = item['path']
                path = evidence_path(rel)
                source = directory / 'witnesses' / rel
                require(source.is_file() and not source.is_symlink()
                        and digest(source.read_bytes()) == item['sha256'], 'witness-integrity',
                        f'attempt {n}: {rel} differs from its preserved digest')
                overlay[rel] = source
                if len(path.parts) == 2 and path.suffix == '.sh' and WITNESS_ID.fullmatch(path.stem):
                    witnesses[path.stem] = {'id': path.stem, 'path': rel, 'round': n,
                                            'sha256': item['sha256'], 'status': 'active'}
        text = (directory / 'ARTIFACT.md').read_text(encoding='utf-8', errors='replace')
        for wid, reason in OBSOLETE.findall(text):
            if wid in witnesses and reason.strip():
                witnesses[wid].update(status='obsolete', retired_round=n, reason=reason.strip())
    return witnesses, overlay


def execute(clone, rel, logs, timeout):
    """Run one witness in its own process group. Exit 0 is PASS; anything else is not."""
    logs.mkdir(parents=True)
    started = time.monotonic()
    with (logs / 'stdout.txt').open('wb') as out, (logs / 'stderr.txt').open('wb') as err:
        child = None
        try:
            child = subprocess.Popen(['bash', rel], cwd=clone, stdout=out, stderr=err,
                                     stdin=subprocess.DEVNULL, env=child_environment(),
                                     start_new_session=True)
            try:
                rc = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return 'TIMEOUT', None, time.monotonic() - started
        except InterruptedError:
            raise  # a cancelled precheck stops; it is not one more failing witness
        except OSError as error:
            err.write(f'witness could not start: {type(error).__name__}\n'.encode())
            return 'ERROR', None, time.monotonic() - started
        finally:
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
    return ('PASS' if rc == 0 else 'FAIL'), rc, time.monotonic() - started


def precheck(repo, head, witnesses, overlay, output, timeout, disputed):
    """Rerun every active witness in a clean checkout of `head`; no model, no ledger write."""
    rows = []
    active = sorted((w for w in witnesses.values() if w['status'] == 'active'), key=lambda w: w['id'])
    def cancelled(signum, frame):
        raise InterruptedError(f'witness precheck interrupted by {signal.Signals(signum).name}')
    previous = signal.signal(signal.SIGTERM, cancelled)
    try:
        if active:
            output.mkdir(parents=True)
            temp_base = '/private/tmp' if Path('/private/tmp').is_dir() else None
            with tempfile.TemporaryDirectory(prefix='w', dir=temp_base) as temp:
                clone = Path(temp).resolve() / 'repo'
                cloned = run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', repo, clone])
                require(cloned.returncode == 0, 'witness-checkout', cloned.stderr.decode().strip())
                for witness in active:
                    for command in (['checkout', '--quiet', '--force', '--detach', head],
                                    ['clean', '-ffdxq']):
                        result = run(['git', '-C', clone, *command])
                        require(result.returncode == 0, 'witness-checkout',
                                f'cannot reset the witness checkout to {head}')
                    _, notes = prepare(clone, overlay)
                    script = clone / witness['path']
                    if (script.is_symlink() or not script.is_file()
                            or digest(script.read_bytes()) != witness['sha256']):
                        # The tree under review supplies this path, so running it would let the
                        # repair stand in for the reviewer's witness.
                        rows.append(dict(witness, result='ERROR', exit=None, seconds=0.0,
                                         notes=notes + ['the reviewed tree replaces this witness'],
                                         disputed=witness['id'] in disputed))
                        continue
                    result, rc, seconds = execute(clone, witness['path'], output / witness['id'], timeout)
                    rows.append(dict(witness, result=result, exit=rc, seconds=seconds, notes=notes,
                                     disputed=witness['id'] in disputed))
    finally:
        signal.signal(signal.SIGTERM, previous)
    return rows


def blocking(rows):
    return [row['id'] for row in rows if row['result'] != 'PASS' and not row['disputed']]


def results_markdown(head, rows, witnesses, output=None):
    lines = ['# Witness results', '', f'Head: {head}', '']
    retired = [w for w in witnesses.values() if w['status'] == 'obsolete']
    if not rows:
        lines.append('No active preserved witness for this review sequence.')
    else:
        lines += ['Each active witness ran in a clean checkout of this head with review_evidence/ '
                  'restored. PASS means it exited 0. It supports closure only if the witness failed at '
                  'its origin head and still exercises its finding.', '',
                  '| witness | from attempt | result | exit | seconds | note |',
                  '|---|---|---|---|---|---|']
        for row in rows:
            note = '; '.join((['failing, disputed by the implementer'] if row['disputed']
                              and row['result'] != 'PASS' else []) + row['notes'])
            exit_code = '' if row['exit'] is None else row['exit']
            lines.append(f"| {row['id']} | {row['round']} | {row['result']} | {exit_code} | "
                         f"{row['seconds']:.1f} | {note.replace('|', '/')} |")
    if retired:
        lines += ['', 'Retired witnesses, not run:']
        lines += [f"- {w['id']} (from attempt {w['round']}), retired in attempt {w['retired_round']}: "
                  f"{w['reason']}" for w in sorted(retired, key=lambda w: w['id'])]
    if output is not None:
        lines += ['', f'Logs: {output}']
    return '\n'.join(lines) + '\n'


def ledger_rows(witnesses):
    return [f"- {w['id']} from attempt {w['round']}: " +
            ('active' if w['status'] == 'active' else
             f"retired in attempt {w['retired_round']}: {w['reason']}")
            for w in sorted(witnesses.values(), key=lambda w: w['id'])]
