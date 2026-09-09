"""Consumer identities are host configuration, never skill content."""
import json
from pathlib import Path
import sys


def check(directory, config):
    """No configured consumer's identity may appear in the portable skill.

    There was a `"self"` exception here, for the repository the skill lives in: its name is the
    skill's own name, so registering it as a consumer would forbid the skill from mentioning
    itself. That registration is gone -- installing the consumer hook on this repository made
    every commit here a full run of the skill's own suite -- and the exception goes with it. An
    exception nobody uses is worse than none: the next reader takes it for a requirement.
    """
    consumers = json.loads(Path(config).read_text())['consumers']
    markers = set()
    for c in consumers:
        markers.add(str(c['repository']).lower())
        markers.add(Path(c['repository']).name.lower())
        markers.update(str(m).lower() for m in c.get('markers', []) if str(m))
    markers.discard('')
    for path in Path(directory).rglob('*'):
        # A .pyc embeds the absolute path it was compiled from, so a stale __pycache__ makes
        # this check fail on a build artifact that is git-ignored and never shipped.
        if '__pycache__' in path.parts:
            continue
        if path.is_file():
            content = path.read_bytes().lower()
            for marker in markers:
                if marker.encode() in content:
                    raise ValueError(f'GUARD FAIL [portability] {path.relative_to(directory)} contains a configured consumer identity')


if __name__ == '__main__':
    try:
        check(sys.argv[1], sys.argv[2])
    except (ValueError, OSError, KeyError) as e:
        sys.exit(str(e))
