#!/usr/bin/env bash
# Install from a maintainer-selected skill version. Never update the trusted suite from a candidate commit.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 - "$HERE" "${1:?repository}" "${REVIEW_CONSUMERS_CONFIG:-}" <<'PY'
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
scripts, repo, config = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), sys.argv[3]
try:
    hooks = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', '--git-path', 'hooks']).decode().strip()
    hooks = (repo / hooks).resolve()
    hooks.mkdir(parents=True, exist_ok=True)
    trusted = hooks / 'sol-simplify-review'
    hook = hooks / 'pre-commit'
    previous = hooks / 'pre-commit.before-review'
    if hook.exists() and 'sol-simplify-review installed hook' not in hook.read_text():
        if previous.exists():
            sys.exit('review-hook: existing hook backup already exists; resolve the two hooks before installing')
        shutil.copy2(hook, previous)
    trusted.mkdir(exist_ok=True)
    # This directory is owned by this installer. Retired code is not part of the selected version.
    if scripts.resolve() != (trusted / 'scripts').resolve():
        if (trusted / 'scripts').exists():
            shutil.rmtree(trusted / 'scripts')
        shutil.copytree(scripts, trusted / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    if (scripts.parent / 'SKILL.md').resolve() != (trusted / 'SKILL.md').resolve():
        shutil.copy2(scripts.parent / 'SKILL.md', trusted / 'SKILL.md')
    default = scripts.parents[2] / 'dogfood/consumers.json'
    if config or default.exists():
        source_config = Path(config or default)
        if source_config.resolve() != (trusted / 'consumers.json').resolve():
            shutil.copy2(source_config, trusted / 'consumers.json')
    driver = shlex.quote(str(trusted / 'scripts/lib/commit-check.py'))
    host = shlex.quote(str(trusted))
    before = shlex.quote(str(previous))
    hook.write_text(f'''#!/bin/sh
# sol-simplify-review installed hook
set -eu
python3 {driver} "$(git rev-parse --show-toplevel)" {host}
if [ -x {before} ]; then exec {before} "$@"; fi
''')
    hook.chmod(0o755)
    print(f'review-hook: installed {hook}; tests come from {trusted}')
except (OSError, subprocess.CalledProcessError) as e:
    sys.exit('review-hook: ' + str(e).replace('\n', '; '))
PY
