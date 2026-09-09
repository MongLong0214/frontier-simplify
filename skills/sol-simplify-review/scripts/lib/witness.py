"""Replay one unchanged, top-level Node test against two exact commits. No model verdicts."""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile

from protocol import digest, require, Rejected

HERE = Path(__file__).resolve().parent


def environment():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    for key in ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_PREFIX', 'GIT_COMMON_DIR',
                'GIT_OBJECT_DIRECTORY', 'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'NODE_OPTIONS'):
        env.pop(key, None)
    return env


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], env=environment(), stderr=subprocess.PIPE)


def run_named(checkout, file, name, output, timeout=60):
    """Accept only a unique, unskipped named test result, never a process failure as a kill."""
    # Escape for JavaScript's RegExp, whose accepted escapes differ from Python's re.escape.
    pattern = '^' + re.sub(r'([\\^$.*+?()\[\]{}|])', r'\\\1', name) + '$'
    command = ['node', '--test', '--test-reporter=' + str(HERE / 'node-witness-reporter.mjs'),
               '--test-name-pattern=' + pattern, file]
    (output / 'command.txt').write_text('\n'.join(command) + '\n')
    with (output / 'events.jsonl').open('wb') as stdout, (output / 'stderr.txt').open('wb') as stderr:
        child = subprocess.Popen(command, cwd=checkout, env=environment(), stdout=stdout,
                                 stderr=stderr, stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            rc = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            (output / 'exit.txt').write_text('TIMEOUT\n')
            raise Rejected('GUARD FAIL [witness-timeout] no completed named assertion')
    (output / 'exit.txt').write_text(str(rc) + '\n')
    rows = [json.loads(line) for line in (output / 'events.jsonl').read_text().splitlines()]
    named = [r for r in rows if r.get('name') == name and r.get('file') and
             Path(r['file']).resolve() == (checkout / file).resolve()]
    require(len(named) == 1, 'witness-selection', 'expected exactly one result for the named test in its file')
    result = named[0]
    require(result.get('kind') == 'test' and result.get('line') and
            not result.get('skip') and not result.get('todo'), 'witness-selection',
            'a suite, wrapper, skipped or TODO test is not an executed witness')
    if result['type'] == 'test:pass':
        require(rc == 0, 'witness-process', 'named test passed but its process failed')
        return 'PASS'
    require(rc > 0 and result.get('code') == 'ERR_ASSERTION' and
            result.get('failure') == 'testCodeFailure', 'witness-assertion',
            'the named test did not fail through an assertion; inspect raw events')
    return 'ASSERTION_FAILED'


def replay(repo, before, after, file, name, source, lesson, output, timeout=60):
    repo, source, output = Path(repo).resolve(), Path(source).resolve(), Path(output).resolve()
    require(not output.is_relative_to(repo), 'witness-location', 'keep replay output outside the consumer checkout')
    path = Path(file)
    require(not path.is_absolute() and '..' not in path.parts and path.suffix == '.mjs',
            'witness-path', 'name a repository-relative .mjs test file')
    before, after = [git(repo, 'rev-parse', '--verify', ref + '^{commit}').decode().strip()
                     for ref in (before, after)]
    require(before != after, 'witness-target', 'before and after must be distinct commits')
    test = git(repo, 'show', f'{after}:{file}')
    source_bytes = source.read_bytes()
    require(test.strip() and source_bytes.strip() and lesson.strip() and name.strip(),
            'witness-input', 'test, test name, source review and lesson must be nonempty')
    # A failed replay cannot leave an older successful lead at this destination.
    output.mkdir(parents=True, exist_ok=False)
    version = subprocess.check_output(['node', '--version'], env=environment()).decode().strip()
    facts = (f'Before: {before}\nAfter: {after}\nNode: {version}\nTest: {file}\nName: {name}\n'
             f'Unchanged test SHA-256: {digest(test)}\nSource review: {source}\n'
             f'Source review SHA-256: {digest(source_bytes)}\n')
    (output / 'REPLAY.txt').write_text(facts)
    outcomes = []
    for label, head in [('before', before), ('after', after)]:
        logs = output / label
        logs.mkdir()
        with tempfile.TemporaryDirectory(prefix='witness-', dir='/tmp') as temp:
            checkout = Path(temp).resolve() / 'repo'
            subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', str(repo), str(checkout)],
                           env=environment(), check=True, stderr=subprocess.PIPE)
            git(checkout, 'checkout', '--quiet', '--detach', head)
            target = checkout / file
            require(target.resolve().is_relative_to(checkout) and not target.is_symlink(),
                    'witness-path', 'test path escapes the disposable checkout')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(test)
            outcome = run_named(checkout, file, name, logs, timeout)
            require(target.read_bytes() == test, 'witness-bytes', 'execution changed the witness')
            outcomes.append(outcome)
            with (output / 'REPLAY.txt').open('a') as out:
                out.write(f'{label}: {outcome}; events SHA-256: {digest((logs / "events.jsonl").read_bytes())}\n')
    require(outcomes == ['ASSERTION_FAILED', 'PASS'], 'witness-contrast',
            'need the same named assertion failing before and passing after; no lead published')
    lead = ('Replayed review lead, selected by the host; investigate its applicability to this change.\n'
            + lesson.strip() + '\n\n' + (output / 'REPLAY.txt').read_text()
            + 'Observed contrast: named assertion failed before and passed after.\n'
            'This does not establish causal attribution to the source review, independent recurrence, '
            'complete coverage, reviewer recall or merge safety. Source prose was not parsed.\n')
    (output / 'LEAD.md').write_text(lead)
    return lead


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for field in ('repository', 'before', 'after', 'file', 'name', 'source_review', 'output'):
        p.add_argument(field)
    p.add_argument('--lesson', required=True, help='host-selected question; never inferred from a verdict')
    p.add_argument('--timeout', type=float, default=60, help='seconds per named test process')
    a = p.parse_args()
    try:
        require(a.timeout > 0, 'witness-timeout', 'timeout must be positive')
        print(replay(a.repository, a.before, a.after, a.file, a.name, a.source_review,
                     a.lesson, a.output, a.timeout))
        return 0
    except (Rejected, OSError, ValueError, subprocess.CalledProcessError) as e:
        print('Witness replay unavailable: ' + str(e), file=sys.stderr)
        return 5


if __name__ == '__main__':
    sys.exit(main())
