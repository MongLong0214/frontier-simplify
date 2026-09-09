#!/usr/bin/env python3
"""Install the selected consumer poller on this macOS host; auto mode deduplicates inputs."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--interval', type=int, required=True, help='seconds between PR discovery runs')
p.add_argument('--artifacts', type=Path, required=True, help='private host evidence directory')
p.add_argument('--config', type=Path, default=Path(os.environ.get('REVIEW_CONSUMERS_CONFIG',
               str(Path(__file__).resolve().with_name('consumers.json')))), help='consumer configuration file')
a = p.parse_args()
if a.interval <= 0:
    p.error('--interval must be positive')
here = Path(__file__).resolve().parent
label = 'dev.sol-simplify.review-dogfood'
path = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
try:
    a.artifacts = a.artifacts.expanduser().resolve()
    config = a.config.expanduser().resolve(strict=True)
    env = {key: value for key, value in os.environ.items() if key in {
        'PATH', 'CODEX_HOME', 'REVIEW_EXECUTOR', 'REVIEW_CODEX_MODEL', 'REVIEW_TIMEOUT',
        'REVIEW_REQUIREMENTS', 'REVIEW_ROUTED', 'REVIEW_CATALOG', 'REVIEW_SUITE_STATUS',
        'REVIEW_TOOL_NOTES', 'REVIEW_LESSONS',
    }}
    env.update(REVIEW_ARTIFACTS=str(a.artifacts), REVIEW_CONSUMERS_CONFIG=str(config))
    path.parent.mkdir(parents=True, exist_ok=True)
    a.artifacts.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as f:
        plistlib.dump({'Label': label, 'ProgramArguments': [sys.executable, str(here / 'run.py')],
                      'WorkingDirectory': str(here.parent), 'StartInterval': a.interval,
                      'RunAtLoad': True,
                      'EnvironmentVariables': env,
                      'StandardOutPath': str(a.artifacts / 'dogfood.log'),
                      'StandardErrorPath': str(a.artifacts / 'dogfood.err')}, f)
    subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True)
    print(f'dogfood: installed {path}')
except (OSError, subprocess.CalledProcessError) as e:
    sys.exit('dogfood: ' + str(e).replace('\n', '; '))
