#!/usr/bin/env python3
"""Harvest attributed review leads. Repetition is not independent evidence or an obligation."""
import re
import sys
from pathlib import Path

CANDIDATE = re.compile(r'^- catalog_candidate:\s*(.+?)\s*$', re.M)


def normalise(text):
    body = re.sub(r'[`*_"“”]', '', text).strip()
    body = re.split(r'\s+(?:--|—|–)\s+', body, maxsplit=1)[0]
    return re.sub(r'\s+', ' ', body).strip(' .').lower()


def harvest(root):
    found = {}
    for artifact in sorted(Path(root).glob('round-*/ARTIFACT.md')):
        for raw in CANDIDATE.findall(artifact.read_text(encoding='utf-8', errors='replace')):
            key = normalise(raw)
            if not key or key in {'none', 'n/a', 'not applicable'} or key.startswith('<'):
                continue
            verbatim, rounds = found.get(key, (raw.strip(), set()))
            found[key] = (verbatim, rounds | {artifact.parent.name})
    return found


def render(found):
    if not found:
        return 'none'
    out = ["Review leads from this PR's artifacts, including rejected reviews. These are reviewer "
           "claims, not verified recurrence or mandatory classes. Check current code and source "
           "evidence; repeated rounds on one change are not independent changes.\n"]
    for verbatim, rounds in found.values():
        out.append('- %s [source: %s]\n' % (verbatim, ', '.join(sorted(rounds))))
    return ''.join(out)


if __name__ == '__main__':
    sys.stdout.write(render(harvest(sys.argv[1])))
