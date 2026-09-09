#!/usr/bin/env python3
"""One consumer discovery pass; unchanged inputs do not launch another automatic review."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--status', action='store_true', help='read PR review status without fetching or calling a model')
a = p.parse_args()
config = Path(os.environ.get('REVIEW_CONSUMERS_CONFIG', str(HERE / 'consumers.json')))
runner = HERE.parent / 'skills/sol-simplify-review/scripts/review-pr.sh'
failed = False
for consumer in json.loads(config.read_text())['consumers']:
    repo = consumer['repository']
    try:
        prs = json.loads(subprocess.check_output(['gh', 'pr', 'list', '--state', 'open', '--json', 'number',
                                                 '--limit', '1000'], cwd=repo, timeout=30))
        print(f'dogfood: {repo}: {len(prs)} open PRs', flush=True)
        for pr in prs:
            env = dict(os.environ)
            if consumer.get('lessons'):
                env['REVIEW_LESSONS'] = consumer['lessons']
            p = subprocess.run([str(runner), repo, str(pr['number']), 'status' if a.status else 'auto'], env=env)
            # A budget handoff is terminal, not an infrastructure error or approval.
            failed |= p.returncode not in ({0} if a.status else {10, 11})
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        print(f'dogfood: {repo}: {e}', file=sys.stderr)
        failed = True
sys.exit(bool(failed))
