#!/usr/bin/env python3
"""Read-only PR discovery; fetch and review in the host's clone, never in the consumer."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from protocol import digest, git, require, Rejected, review_context, artifact_root, child_environment, FAILED
import catalog
import ledger

SCRIPTS = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('runner', SCRIPTS / 'lib/run-review.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('repository', nargs='?', default=os.environ.get('REVIEW_CONSUMER_REPO'))
    p.add_argument('pr', type=int)
    p.add_argument('phase', choices=['1', '2', 'auto', 'status', 'report', 'hunks', 'witnesses'],
                   nargs='?', default='auto')
    p.add_argument('executor', nargs='?', default=os.environ.get('REVIEW_EXECUTOR', 'codex'))
    p.add_argument('--supplementary', action='store_true',
                   help='review beyond the automatic attempts, under an explicit recorded grant')
    p.add_argument('--granted-by', default='', help='who granted the supplementary budget')
    p.add_argument('--budget', type=int, help='supplementary reviews granted for this PR in total')
    a = p.parse_args()
    require(a.repository and a.pr > 0, 'consumer', 'repository and positive PR number are required')
    repo = Path(a.repository).resolve()
    origin = git(repo, 'remote', 'get-url', 'origin').decode().strip()
    root = artifact_root()
    require(not root.is_relative_to(repo), 'host-location', 'artifact root must be outside consumer checkout')
    # Stable across consumer worktrees; the trusted host supplies the remote and PR identity.
    host = root / 'consumers' / digest(origin.encode())[:16]
    mirror = host / 'repository'
    if a.phase == 'report':
        # Stored evidence does not depend on current PR metadata, network access, prompt
        # inputs or the fetch lock. Do not create a mirror just to report no history.
        if mirror.exists():
            ledger.report(runner.root_for(mirror, str(a.pr)), mirror)
        else:
            print('NOT_REVIEWED: no local review history')
        return 0
    def metadata_for_pr():
        data = json.loads(subprocess.check_output(['gh', 'pr', 'view', str(a.pr), '--json',
                         'number,headRefOid,baseRefOid,url'], cwd=repo, timeout=30,
                         env=child_environment()))
        require(data['number'] == a.pr, 'consumer', 'PR metadata identity mismatch')
        return data
    metadata = metadata_for_pr()
    head, target = metadata['headRefOid'], metadata['baseRefOid']
    os.environ['REVIEW_TARGET_OID'] = target
    os.environ['REVIEW_REPOSITORY_NAME'] = origin
    response = Path(os.environ.get('REVIEW_RESPONSE', str(host / f'pr-{a.pr}-response.md')))
    if response.exists():
        os.environ['REVIEW_RESPONSE'] = str(response)
    redesign = Path(os.environ.get('REVIEW_REDESIGN', str(host / f'pr-{a.pr}-redesign.md')))
    if redesign.exists():
        os.environ['REVIEW_REDESIGN'] = str(redesign)
    leads = [os.environ.get('REVIEW_CATALOG', '')]
    lessons = os.environ.get('REVIEW_LESSONS')
    if lessons:
        directory = Path(lessons)
        require(directory.is_dir(), 'consumer', 'REVIEW_LESSONS directory is missing')
        leads += [p.read_text() for p in sorted(directory.glob('*/LEAD.md'))]
    os.environ['REVIEW_CATALOG'] = '\n\n'.join(s for s in leads if s.strip() and s.strip() != 'none') or 'none'
    if a.phase == 'status':
        if not mirror.exists():
            print(f'NOT_REVIEWED: requested head {head}; no local review history')
        else:
            response_bytes = response.read_bytes() if os.environ.get('REVIEW_RESPONSE') else None
            redesign_bytes = redesign.read_bytes() if os.environ.get('REVIEW_REDESIGN') else None
            ledger.status(runner.root_for(mirror, str(a.pr)), mirror, head,
                          context=review_context(SCRIPTS, a.executor, response_bytes, redesign_bytes))
        return 0
    host.mkdir(parents=True, exist_ok=True)
    with (host / '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Rejected('review-pr: repository fetch already running; try status shortly')
        if not mirror.exists():
            subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', str(repo), str(mirror)],
                           env=child_environment(), check=True)
            git(mirror, 'remote', 'set-url', 'origin', origin)
        # Exact SHAs, not mutable branch names. No push, comments, or merge mutation.
        git(mirror, 'fetch', '--quiet', 'origin', head, target)
        base = git(mirror, 'merge-base', target, head).decode().strip()
        (host / f'pr-{a.pr}.json').write_text(json.dumps(metadata, indent=2) + '\n')
    # The mirror is a --no-checkout object store: its working tree is empty and its index still
    # lists every file, so `git status` there reports the base commit with hundreds of staged
    # deletions. Naming it to the reviewer as "Repository" sends the reviewer to a tree that is
    # not the reviewed head -- measured: a round spent its opening moves discovering that and
    # building its own checkout, and a less careful reviewer would have reviewed the base.
    # The reviewer's own cwd is the correct disposable checkout; the prompt gets the identity.
    # History supplies attributed leads, never required IDs or self-promoted obligations.
    notices = []
    if a.phase in {'1', '2', 'auto'}:
        ledger_root = runner.root_for(mirror, str(a.pr))
        os.environ['REVIEW_HISTORY'] = catalog.render(catalog.harvest(ledger_root))
        notices.append('review-pr: project history supplied as leads, not standing obligations')
    argv = [a.phase, str(mirror), head, str(a.pr), base, a.executor]
    if a.supplementary or a.granted_by or a.budget is not None:
        argv += ['--supplementary'] * a.supplementary + ['--granted-by', a.granted_by]
        argv += ['--budget', str(a.budget)] if a.budget is not None else []
    notices.append(f'review-pr: consumer host {host}')
    def still_current():
        current = metadata_for_pr()
        require((current['headRefOid'], current['baseRefOid']) == (head, target),
                'stale-pr', f'PR changed during review; reviewed {head} against {target}, '
                f'current {current["headRefOid"]} against {current["baseRefOid"]}')
    # Cache selection and round allocation share the same lock, including cached returns.
    return runner.main(argv, freshness_check=still_current, notices=notices)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Rejected, OSError, ValueError, KeyError, subprocess.SubprocessError) as e:
        print('review-pr: ' + str(e).replace('\n', '; '), file=sys.stderr)
        sys.exit(FAILED)
