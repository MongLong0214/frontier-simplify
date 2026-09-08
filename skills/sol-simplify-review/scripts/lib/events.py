"""Read executor envelopes, never count an event-shaped string inside assistant prose."""
import json
from pathlib import Path
import sys


def inspect(path):
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    commands = 0
    completed = False
    for e in events:
        if e.get('type') in {'turn.failed', 'error'}:
            raise ValueError('executor reported failure')
        if e.get('type') == 'turn.started':
            completed = False
        if e.get('type') == 'turn.completed':
            completed = True
        if e.get('type') == 'result':
            if e.get('is_error') or e.get('subtype', 'success') != 'success':
                raise ValueError('executor result was not successful')
            completed = True
        item = e.get('item') or {}
        if e.get('type') == 'item.completed' and item.get('type') == 'command_execution':
            commands += 1
        if e.get('type') == 'assistant':
            commands += sum(c.get('type') == 'tool_use' for c in
                            (e.get('message') or {}).get('content', []))
    return completed, commands


if __name__ == '__main__':
    try:
        completed, count = inspect(sys.argv[2])
        if sys.argv[1] == 'completed' and not completed:
            raise ValueError('no successful completion event')
        if sys.argv[1] == 'commands' and not count:
            raise ValueError('reviewer executed 0 tools')
        print(count)
    except (ValueError, OSError, TypeError, AttributeError) as e:
        sys.exit(f'GUARD FAIL [events-{sys.argv[1]}] {e}')
