"""Consumer identities are host configuration, never skill content."""
import json
from pathlib import Path
import sys


def check(directory, config):
    consumers = json.loads(Path(config).read_text())['consumers']
    markers = {str(m).lower() for c in consumers for m in
               [c['repository'], Path(c['repository']).name, *c.get('markers', [])] if str(m)}
    for path in Path(directory).rglob('*'):
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
