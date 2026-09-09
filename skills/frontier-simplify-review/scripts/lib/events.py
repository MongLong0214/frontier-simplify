"""Read executor envelopes, never count an event-shaped string inside assistant prose."""
import json
from pathlib import Path
import sys


def inspect(path):
    events = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    commands = 0
    completed = False
    failure = None
    for e in events:
        # An error frame is not by itself a failed round. Measured: a transport dropped mid-run,
        # logged four reconnect errors, recovered, and closed a 58KB inventory with `turn.completed`
        # as the last event and exit 0 -- and this refused it as "executor reported failure". The
        # file distinguishes them without loosening anything: an error that is followed by a
        # completion was survived, and an error that ends the stream was not. So the failure is
        # remembered rather than raised, and only stands if nothing completes after it.
        if e.get('type') in {'turn.failed', 'error'}:
            failure = 'executor reported failure'
            completed = False
        if e.get('type') == 'turn.started':
            completed = False
        if e.get('type') == 'turn.completed':
            completed, failure = True, None
        if e.get('type') == 'result':
            if e.get('is_error') or e.get('subtype', 'success') != 'success':
                raise ValueError('executor result was not successful')
            completed, failure = True, None
        item = e.get('item') or {}
        if e.get('type') == 'item.completed' and item.get('type') == 'command_execution':
            commands += 1
        if e.get('type') == 'assistant':
            commands += sum(c.get('type') == 'tool_use' for c in
                            (e.get('message') or {}).get('content', []))
    # Stands only if nothing completed after it: an error that ends the stream failed the round,
    # an error the round outlived did not.
    if failure:
        raise ValueError(failure)
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
