#!/usr/bin/env python3
"""Read-only PR discovery; fetch and review in the host's clone, never in the consumer."""
import argparse
import fcntl
import json
import re
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
    # The project's own rounds are its catalog. SKILL.md asks every item for a
    # `catalog_candidate` and states when one earns a standing entry; nothing collected them,
    # so nine rounds on one PR emitted thirty-eight candidates -- one of which said in its own
    # words "this is the third time" and named the three sites -- while every round after the
    # first began from `none` and rediscovered the class at a new site. Harvesting them is what
    # makes using this protocol improve it, rather than only improving what it is pointed at.
    # An explicit REVIEW_CATALOG still wins: the host may always override what it feeds back.
    if not os.environ.get('REVIEW_CATALOG'):
        # Ask the runner where this PR's rounds live rather than rebuilding the path here. The
        # first version pointed at the consumer host directory, which holds the mirror and the PR
        # metadata but no round artifacts, so the harvest found nothing and injected nothing --
        # silently. A feedback loop that no-ops is worse than one that is missing: nothing says it
        # is not working, and the rounds go on rediscovering the class it was built to carry.
        ledger_root = subprocess.run([str(SCRIPTS / 'review-round.sh'), 'path', str(mirror),
                                      head, str(a.pr)], capture_output=True, text=True)
        if ledger_root.returncode == 0 and ledger_root.stdout.strip():
            harvested = subprocess.run([sys.executable, str(SCRIPTS / 'lib/catalog.py'),
                                        ledger_root.stdout.strip()], capture_output=True, text=True)
            ids = re.findall(r'^P-\d+', harvested.stdout, re.M)
            # Only a catalog with standing classes is worth supplying. The renderer also prints
            # candidates "raised once, not yet standing", and handing those over as a catalog made
            # the runner demand ids for classes that do not exist: the run said it had carried
            # forward nothing and then refused for a missing P-01 in the same breath. Leads are
            # not obligations, which is what the renderer says about them.
            if harvested.returncode == 0 and ids:
                os.environ['REVIEW_CATALOG'] = harvested.stdout
                # A supplied catalog is only supplied if the inventory has to answer for it. The
                # runner checks that every declared class was instantiated, and it learns which
                # ones from REVIEW_EXPECTED_IDS -- so handing over the text without the ids makes
                # the classes optional, which is the same as not carrying them. Derived from the
                # rendered catalog rather than tracked beside it: two lists of the same thing is
                # how one goes stale.
                if not os.environ.get('REVIEW_EXPECTED_IDS'):
                    os.environ['REVIEW_EXPECTED_IDS'] = ','.join(ids)
                # Count the classes as classes and the rounds as rounds. Printing one number
                # under the other's name is how "carried forward from 0" appeared above a refusal
                # that named a class.
                seen = len(list(Path(ledger_root.stdout.strip()).glob('round-*/ARTIFACT.md')))
                print('review-pr: %d standing class(es) carried forward from %d round(s): %s'
                      % (len(ids), seen, ', '.join(ids)), file=sys.stderr)
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
