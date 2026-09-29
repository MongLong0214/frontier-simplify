#!/usr/bin/env python3
"""Finite witness timeout and owned child-group lifecycle regressions."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS / 'lib'))
import witness
from protocol import Rejected


def check(name, value):
    print(('ok   ' if value else 'NOT OK ') + name)
    return value


def stopped(pid):
    state = subprocess.run(['ps', '-o', 'stat=', '-p', str(pid)], capture_output=True,
                           text=True).stdout.strip()
    return not state or state.startswith('Z')


def eventually_stopped(pid):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if stopped(pid):
            return True
        time.sleep(0.05)
    return stopped(pid)


def fixture(checkout, pidfile, waiting=False):
    (checkout / 'probe.test.mjs').write_text('''
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { writeFileSync } from 'node:fs';
test('named witness', async () => {
  const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'],
                      { stdio: 'ignore' });
  writeFileSync(''' + json.dumps(str(pidfile)) + ''', String(child.pid));
  child.unref();
  assert.equal(1, 1);
''' + ('  await new Promise(resolve => setTimeout(resolve, 60000));\n' if waiting else '') + '''});
''')


with tempfile.TemporaryDirectory(prefix='review-witness-test-') as temporary:
    t = Path(temporary)
    checkout = t / 'checkout'
    checkout.mkdir()
    results = []
    for number, timeout in enumerate((float('nan'), float('inf'), float('-inf'), 0, -1), 1):
        output = t / f'invalid-{number}'
        output.mkdir()
        with patch.object(witness.subprocess, 'Popen', side_effect=RuntimeError('launched')) as popen:
            try:
                witness.run_named(checkout, 'probe.test.mjs', 'named witness', output, timeout)
            except Rejected as error:
                rejected = '[witness-timeout]' in str(error)
            except Exception:
                rejected = False
        results.append(check(f'invalid-timeout-{number}-launches-zero',
                             rejected and popen.call_count == 0 and not list(output.iterdir())))
    direct_output = t / 'direct-invalid'
    try:
        witness.replay(t / 'missing-repo', 'before', 'after', 'probe.test.mjs',
                       'named witness', t / 'missing-source', 'question', direct_output,
                       float('inf'))
    except Rejected as error:
        rejected = '[witness-timeout]' in str(error)
    except Exception:
        rejected = False
    results.append(check('public-replay-refuses-nonfinite-before-output',
                         rejected and not direct_output.exists()))
    cli_output = t / 'cli-invalid'
    cli = subprocess.run([sys.executable, '-B', str(SCRIPTS / 'lib/witness.py'),
                          str(t / 'missing-repo'), 'before', 'after', 'probe.test.mjs',
                          'named witness', str(t / 'missing-source'), str(cli_output),
                          '--lesson', 'question', '--timeout', 'inf'],
                         capture_output=True, text=True)
    results.append(check('cli-refuses-nonfinite-before-output',
                         cli.returncode == 5 and '[witness-timeout]' in cli.stderr
                         and not cli_output.exists()))

    exception_pidfile = t / 'wait-exception.pid'
    fixture(checkout, exception_pidfile, waiting=True)
    exception_output = t / 'wait-exception'
    exception_output.mkdir()
    real_popen = subprocess.Popen
    def failing_wait_process(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        real_wait = process.wait
        def failing_wait(*wait_args, **wait_kwargs):
            until = time.monotonic() + 5
            while not exception_pidfile.exists() and process.poll() is None and time.monotonic() < until:
                time.sleep(0.02)
            process.wait = real_wait
            raise RuntimeError('wait failed')
        process.wait = failing_wait
        return process
    with patch.object(witness.subprocess, 'Popen', failing_wait_process):
        try:
            witness.run_named(checkout, 'probe.test.mjs', 'named witness', exception_output, 10)
        except RuntimeError as error:
            raised = str(error) == 'wait failed'
        else:
            raised = False
    exception_pid = int(exception_pidfile.read_text()) if exception_pidfile.exists() else None
    exception_clean = eventually_stopped(exception_pid) if exception_pid else False
    if exception_pid and not exception_clean:
        os.kill(exception_pid, signal.SIGKILL)
    results.append(check('wait-exception-reaps-owned-group',
                         raised and exception_clean and not (exception_output / 'exit.txt').exists()))

    runner_script = '''
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import witness
from protocol import Rejected
try:
    witness.run_named(Path(sys.argv[2]), 'probe.test.mjs', 'named witness', Path(sys.argv[3]), 10)
except Rejected as error:
    print(error, file=sys.stderr)
    sys.exit(5)
'''
    for label, waiting, interruption in [('success', False, None),
                                          ('timeout', True, None),
                                          ('sigint', True, signal.SIGINT),
                                          ('sigterm', True, signal.SIGTERM)]:
        pidfile = t / (label + '.pid')
        fixture(checkout, pidfile, waiting)
        output = t / label
        output.mkdir()
        if interruption:
            proc = subprocess.Popen([sys.executable, '-B', '-c', runner_script,
                                     str(SCRIPTS / 'lib'), str(checkout), str(output)],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            until = time.monotonic() + 10
            while not pidfile.exists() and proc.poll() is None and time.monotonic() < until:
                time.sleep(0.05)
            ready = pidfile.exists()
            if ready:
                proc.send_signal(interruption)
            try:
                _, error_text = proc.communicate(timeout=10)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
            code = proc.returncode
            reason = error_text
        else:
            try:
                result = witness.run_named(checkout, 'probe.test.mjs', 'named witness', output,
                                           3 if waiting else 10)
            except Rejected as error:
                result, reason, code = None, str(error), 5
            else:
                reason, code = '', 0
            ready = pidfile.exists()
        pid = int(pidfile.read_text()) if ready else None
        clean = eventually_stopped(pid) if pid else False
        if pid and not clean:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if label == 'success':
            good = result == 'PASS' and clean and (output / 'exit.txt').read_text().strip() == '0'
        elif label == 'timeout':
            good = code == 5 and '[witness-timeout]' in reason and clean
        else:
            good = code == 5 and 'witness-cancelled' in reason and clean
        results.append(check(label + '-reaps-owned-group-and-preserves-reason', ready and good))

sys.exit(0 if all(results) else 1)
