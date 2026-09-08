"""Consumer identities are host configuration, never skill content."""
import json
from pathlib import Path
import sys


def check(directory, config):
    """No configured consumer's identity may appear in the portable skill.

    One consumer is different: the repository the skill itself lives in. Its name is the
    skill's own name, so the marker rule would forbid the skill from mentioning itself and
    the repository could never review its own changes -- which is exactly the change most
    worth reviewing, since every commit here edits a merge gate. A consumer marked `"self"`
    contributes its PATHS but not its name: hardcoding where it sits on this disk is still
    the defect the check is for, and knowing what it is called is not.
    """
    consumers = json.loads(Path(config).read_text())['consumers']
    markers = set()
    for c in consumers:
        markers.add(str(c['repository']).lower())
        if not c.get('self'):
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
