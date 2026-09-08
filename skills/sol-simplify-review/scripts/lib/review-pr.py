#!/usr/bin/env python3
"""Read-only PR discovery; fetch and review in the host's clone, never in the consumer."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from protocol import digest, git, require, Rejected

SCRIPTS = Path(__file__).resolve().parent.parent


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('repository', nargs='?', default=os.environ.get('REVIEW_CONSUMER_REPO'))
    p.add_argument('pr', type=int)
    p.add_argument('phase', choices=['1', '2', 'auto', 'report', 'hunks'], nargs='?', default='auto')
    p.add_argument('executor', nargs='?', default=os.environ.get('REVIEW_EXECUTOR', 'codex'))
    a = p.parse_args()
    require(a.repository and a.pr > 0, 'consumer', 'repository and positive PR number are required')
    repo = Path(a.repository).resolve()
    origin = git(repo, 'remote', 'get-url', 'origin').decode().strip()
    root = Path(os.environ.get('REVIEW_ARTIFACTS', str(Path.home() / '.sol-simplify-review'))).resolve()
    require(not root.is_relative_to(repo), 'host-location', 'artifact root must be outside consumer checkout')
    # Stable across consumer worktrees; the trusted host supplies the remote and PR identity.
    host = root / 'consumers' / digest(origin.encode())[:16]
    host.mkdir(parents=True, exist_ok=True)
    mirror = host / 'repository'
    with (host / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not mirror.exists():
            subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', str(repo), str(mirror)], check=True)
            subprocess.run(['git', '-C', str(mirror), 'remote', 'set-url', 'origin', origin], check=True)
        metadata = json.loads(subprocess.check_output(['gh', 'pr', 'view', str(a.pr), '--json',
                                                      'number,headRefOid,baseRefOid,url'], cwd=repo))
        require(metadata['number'] == a.pr, 'consumer', 'PR metadata identity mismatch')
        head, target = metadata['headRefOid'], metadata['baseRefOid']
        # Exact SHAs, not mutable branch names. No push, comments, or merge mutation.
        subprocess.run(['git', '-C', str(mirror), 'fetch', '--quiet', 'origin', head, target], check=True)
        base = git(mirror, 'merge-base', target, head).decode().strip()
        (host / f'pr-{a.pr}.json').write_text(json.dumps(metadata, indent=2) + '\n')
    # The mirror is a --no-checkout object store: its working tree is empty and its index still
    # lists every file, so `git status` there reports the base commit with hundreds of staged
    # deletions. Naming it to the reviewer as "Repository" sends the reviewer to a tree that is
    # not the reviewed head -- measured: a round spent its opening moves discovering that and
    # building its own checkout, and a less careful reviewer would have reviewed the base.
    # The reviewer's own cwd is the correct disposable checkout; the prompt gets the identity.
    os.environ['REVIEW_REPOSITORY_NAME'] = origin
    argv = [str(SCRIPTS / 'review-round.sh'), a.phase, str(mirror), head, str(a.pr), base, a.executor]
    print(f'review-pr: consumer host {host}', file=sys.stderr)
    if a.phase == 'auto':
        # Import only the host-selected runner; never anything from the implementation branch.
        import importlib.util
        spec = importlib.util.spec_from_file_location('runner', SCRIPTS / 'lib/run-review.py')
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        import ledger
        ledger_root = runner.root_for(mirror, str(a.pr))
        starts, ends, originals = ledger.audit(ledger_root, mirror)
        response = Path(os.environ.get('REVIEW_RESPONSE', str(host / f'pr-{a.pr}-response.md')))
        escapes = Path(os.environ.get('REVIEW_ESCAPES', str(host / f'pr-{a.pr}-escapes.md')))
        if response.exists():
            os.environ['REVIEW_RESPONSE'] = str(response)
        if escapes.exists():
            os.environ['REVIEW_ESCAPES'] = str(escapes)
        latest = starts[max(starts)] if starts else None
        if latest and latest['head_sha'] == head:
            end = ends.get(latest['round'], {})
            changed_inputs = any(path.exists() and digest(path.read_bytes()) != latest['inputs'].get(name)
                                 for name, path in [('IMPLEMENTER_RESPONSE.md', response), ('ESCAPES.md', escapes)])
            if end.get('executed') or not changed_inputs:
                ledger.report(ledger_root, mirror)
                fixture_chain = any(s.get('executor') == 'stub' for s in starts.values())
                return 0 if end.get('accepted') and end.get('verdict') in {'PASS', 'PASS WITH NITS'} and not fixture_chain else 5
        argv[1] = '2' if originals else '1'
    return subprocess.run(argv).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        sys.exit('review-pr: ' + str(e).replace('\n', '; '))
