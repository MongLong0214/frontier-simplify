#!/usr/bin/env python3
"""Replay preserved machine evidence for a requested base..head. Never approves a merge."""
import argparse
from pathlib import Path
import subprocess
import sys

import ledger
from protocol import FAILED, Rejected, digest, git, require, review_exit


def replay(root, repo, base, head, out):
    base = git(repo, 'rev-parse', '--verify', base + '^{commit}').decode().strip()
    head = git(repo, 'rev-parse', '--verify', head + '^{commit}').decode().strip()
    starts, ends, originals = ledger.audit(root, repo)
    print(f'Requested target: {base}..{head}', file=out)
    print('Machine evidence only; prose is preserved, never scored. No merge authorization.', file=out)
    available = {}
    for n, start in starts.items():
        end = ends.get(n, {})
        directory = root / f'round-{n:04}'
        checks = ledger.recompute(repo, directory, start) if end.get('executed') else []
        available[n] = ledger.evidence_available(checks, end)
        state = ('AVAILABLE' if available[n] else 'UNAVAILABLE' if end.get('executed') else
                 'NOT_EXECUTED' if end else 'INTERRUPTED')
        print(f'Attempt {n}: phase={start["phase"]} head={start["head_sha"]} '
              f'evidence={state} historical_accepted={bool(end.get("accepted"))}', file=out)
        for check in checks:
            if not check['ok']:
                print(f'  {check["guard"]}: {check["reason"]}', file=out)
    print(f'{len(starts)} attempts; {sum(bool(e.get("executed")) for e in ends.values())} executed; '
          f'{len(originals)} preserved original reviews; '
          f'{sum(bool(e.get("accepted")) and starts[n]["phase"] == 1 for n, e in ends.items())} '
          f'historical accepted inventories; '
          f'{sum(bool(e.get("executed")) and starts[n]["phase"] == 2 for n, e in ends.items())} '
          'phase-2 executions.', file=out)
    refusals = ledger.guard_rejections(ends)
    print('Historical refusals: ' + (', '.join(f'{k}={v}' for k, v in refusals.items()) or 'none'), file=out)
    print('CI, product counts, mutation results and product contract version: '
          'not attested by review receipts. Prompt claims are not measurements.', file=out)
    matching = [n for n, s in starts.items() if s.get('base_sha') == base and s['head_sha'] == head]
    require(matching, 'replay-target', 'no attempt is bound to the requested base..head')
    latest = matching[-1]
    # A later failed/interrupted attempt at this target is not hidden by an earlier good one.
    require(available[latest], 'replay-evidence', f'latest matching attempt {latest} lacks intact execution evidence')
    directory = root / f'round-{latest:04}'
    # The seal is host-generated data, not review prose. A receipt's base label and input hashes
    # alone do not establish that the supplied patch is Git's patch for the requested pair.
    seal_bases = [line for line in (directory / 'SEAL.txt').read_text().splitlines()
                  if line.startswith('base_sha:')]
    require(seal_bases == ['base_sha: ' + base], 'replay-base', 'receipt base differs from the sealed base')
    require((directory / 'DIFF.patch').read_bytes() == git(
        repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', base, head),
        'replay-diff', 'preserved patch differs from Git at the requested base..head')
    require((directory / 'CHANGED.txt').read_bytes() == git(repo, 'diff', '--no-renames', '--name-only', base, head),
            'replay-changed', 'preserved changed-file list differs from Git at the requested base..head')
    artifact = directory / 'ARTIFACT.md'
    print(f'Latest matching attempt: {latest}; artifact_sha256={digest(artifact.read_bytes())}', file=out)
    print('Exit 10: evidence available for human assessment, including any BLOCK or coverage gaps.', file=out)
    return review_exit(True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repository', type=Path)
    parser.add_argument('ledger_directory', type=Path)
    parser.add_argument('base')
    parser.add_argument('head')
    args = parser.parse_args()
    try:
        return replay(args.ledger_directory.resolve(), args.repository.resolve(), args.base, args.head, sys.stdout)
    except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print('Replay unavailable: ' + str(error).replace('\n', '; '), file=sys.stderr)
        return FAILED


if __name__ == '__main__':
    sys.exit(main())
