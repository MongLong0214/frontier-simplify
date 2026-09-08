#!/usr/bin/env python3
"""Run from an existing host scheduler; each PR/head is attempted once by auto mode."""
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
config = Path(os.environ.get('REVIEW_CONSUMERS_CONFIG', str(HERE / 'consumers.json')))
runner = HERE.parent / 'skills/sol-simplify-review/scripts/review-pr.sh'
failed = False
for consumer in json.loads(config.read_text())['consumers']:
    repo = consumer['repository']
    try:
        prs = json.loads(subprocess.check_output(['gh', 'pr', 'list', '--state', 'open', '--json', 'number'], cwd=repo))
        for pr in prs:
            p = subprocess.run([str(runner), repo, str(pr['number']), 'auto'])
            # 10 means evidence was recorded, never that the PR may merge.
            failed |= p.returncode not in {0, 10}
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        print(f'dogfood: {repo}: {e}', file=sys.stderr)
        failed = True
sys.exit(bool(failed))
