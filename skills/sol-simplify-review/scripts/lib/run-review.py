#!/usr/bin/env python3
"""Trusted host: freeze inputs, run one reviewer, recompute guards, append a receipt."""
import argparse
import fcntl
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from protocol import (Rejected, require, git, digest, hunks, hunk_markdown,
                      protocol_sha256, review_context, review_exit, FAILED, HANDOFF, MAX_ROUNDS)
import ledger

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL = SCRIPTS.parent / 'SKILL.md'


def run(args, cwd=None, stdout=subprocess.PIPE):
    return subprocess.run(list(map(str, args)), cwd=cwd, stdout=stdout, stderr=subprocess.PIPE)


def root_for(repo, pr):
    require(bool(pr) and all(c.isalnum() or c in '-_.' for c in pr) and pr not in {'.', '..'},
            'pr-id', 'use one stable PR number or local review ID, never a round suffix')
    common = git(repo, 'rev-parse', '--git-common-dir').decode().strip()
    identity = str((Path(repo) / common).resolve())
    root = Path(os.environ.get('REVIEW_ARTIFACTS', str(Path.home() / '.sol-simplify-review'))).resolve()
    require(not root.is_relative_to(Path(repo).resolve()), 'host-location', 'REVIEW_ARTIFACTS must be outside the consumer checkout')
    return root / digest(identity.encode())[:16] / pr


def freeze(path, data):
    with path.open('xb') as f:
        f.write(data)


def copy_input(source, directory, name):
    freeze(directory / name, Path(source).read_bytes())


def main(argv=None, freshness_check=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['1', '2', 'auto', 'status', 'report', 'path', 'hunks'])
    p.add_argument('repo', type=Path)
    p.add_argument('head', help='commit/ref; ignored for report/path')
    p.add_argument('pr', help='stable PR ID; actual round is assigned by the host')
    p.add_argument('base', nargs='?', default='')
    p.add_argument('executor', nargs='?', default='')
    a = p.parse_args(argv)
    repo = a.repo.resolve()
    root = root_for(repo, a.pr)
    if a.phase == 'path':
        print(root)
        return 0
    executor = a.executor or os.environ.get('REVIEW_EXECUTOR', 'codex')
    def caller_inputs():
        source = os.environ.get('REVIEW_RESPONSE')
        response = Path(source).read_bytes() if source else None
        context = review_context(SCRIPTS, executor, response)
        if os.environ.get('REVIEW_TARGET_BRANCH') and not os.environ.get('REVIEW_TARGET_OID'):
            context['target_sha'] = git(repo, 'rev-parse', '--verify',
                                        os.environ['REVIEW_TARGET_BRANCH'] + '^{commit}').decode().strip()
        return context, response
    if a.phase == 'status':
        head = git(repo, 'rev-parse', '--verify', a.head + '^{commit}').decode().strip()
        base = git(repo, 'rev-parse', '--verify', a.base + '^{commit}').decode().strip() if a.base else None
        ledger.status(root, repo, head, base, caller_inputs()[0])
        return 0
    if a.phase in {'report', 'hunks'}:
        if a.phase == 'report':
            ledger.report(root, repo)
        else:
            _, _, originals = ledger.audit(root, repo)
            require(originals, 'handoff', 'no preserved original review for this PR')
            head = git(repo, 'rev-parse', '--verify', a.head + '^{commit}').decode().strip()
            print(hunk_markdown(hunks(repo, originals[-1][2]['head_sha'], head)), end='')
        return 0
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.lock').open('a') as lock:
        # Non-blocking, and refuse. Waiting looks like a hang from the outside, and a second
        # invocation that reaches the same round directory writes into the events stream the
        # first one is still producing -- reported: two runs interleaved into one
        # events.jsonl, the stream ended without a result event, and the round looked dead
        # while the first run was in fact still going and finished normally.
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            require(False, 'concurrent-round',
                    f'another round is already running for this PR ({root}); wait for it rather '
                    'than starting a second one, which would write into its events stream')
        starts, ends, originals = ledger.audit(root, repo)
        head = git(repo, 'rev-parse', '--verify', a.head + '^{commit}').decode().strip()
        if len(starts) >= MAX_ROUNDS:
            ledger.handoff(root, repo, head)
            return HANDOFF
        context, response = caller_inputs()
        phase = (2 if originals else 1) if a.phase == 'auto' else int(a.phase)
        if a.base:
            base = git(repo, 'rev-parse', '--verify', a.base + '^{commit}').decode().strip()
        elif phase == 2 and originals:
            base = originals[-1][2]['base_sha']
        else:
            target = os.environ.get('REVIEW_TARGET_BRANCH', '')
            require(target, 'base', 'provide merge-base or REVIEW_TARGET_BRANCH; current branch is not a target default')
            base = git(repo, 'merge-base', target, head).decode().strip()
        if a.phase == 'auto' and originals:
            original = originals[-1][2]
            if base != original['base_sha'] or run([
                    'git', '-C', repo, 'merge-base', '--is-ancestor', original['head_sha'], head]).returncode != 0:
                phase = 1

        def check_freshness():
            require(git(repo, 'rev-parse', '--verify', a.head + '^{commit}').decode().strip() == head,
                    'stale-head', 'requested head changed during review')
            if a.base:
                require(git(repo, 'rev-parse', '--verify', a.base + '^{commit}').decode().strip() == base,
                        'stale-base', 'requested base changed during review')
            require(caller_inputs()[0] == context, 'stale-inputs', 'review inputs changed during review')
            if freshness_check:
                freshness_check()

        latest = starts[max(starts)] if starts else None
        if (a.phase == 'auto' and latest and latest['head_sha'] == head
                and latest.get('base_sha') == base and latest.get('context') == context):
            end = ends.get(latest['round'], {})
            ledger.report(root, repo)
            try:
                check_freshness()
            except (Rejected, OSError, ValueError, subprocess.SubprocessError) as e:
                print('review: STALE or unavailable: ' + str(e), file=sys.stderr)
                return FAILED
            available = ledger.evidence_available(ledger.recompute(
                repo, root / f"round-{latest['round']:04}", latest), end)
            return review_exit(available and end.get('fresh_at_finish', True), len(starts))
        n = len(starts) + 1
        d = root / f'round-{n:04}'
        d.mkdir()
        inputs = []
        start = {'event': 'started', 'round': n, 'phase': phase, 'head_sha': head,
                 'base_sha': base, 'repo': str(repo), 'pr': a.pr, 'mode': ledger.MODE,
                 'inputs': {}, 'context': context}
        started = False
        executed = False
        finished = False
        clone = None
        child = None
        old_handlers = {}
        def interrupted(signum, frame):
            raise InterruptedError(f'review interrupted by {signal.Signals(signum).name}')
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.signal(sig, interrupted)
            timeout = float(os.environ.get('REVIEW_TIMEOUT', '1800'))
            require(math.isfinite(timeout) and timeout > 0, 'timeout', 'REVIEW_TIMEOUT must be positive finite seconds')
            require(executor in {'codex', 'claude', 'stub'}, 'executor', 'use codex, claude, or stub')
            require(run(['git', '-C', repo, 'merge-base', '--is-ancestor', base, head]).returncode == 0,
                    'ancestry', 'base is not an ancestor of head')
            if phase == 2:
                require(originals, 'handoff', 'follow-up requires a preserved original review')
                _, original_dir, original_start, inventory = originals[-1]
                require(base == original_start['base_sha'], 'scope-change', 'RESTART_ROUND_1: base changed')
                r1head = original_start['head_sha']
                require(run(['git', '-C', repo, 'merge-base', '--is-ancestor', r1head, head]).returncode == 0,
                        'ancestry', 'RESTART_ROUND_1: remediation does not descend from round 1')
                start.update(round1_head_sha=r1head, inventory_sha256=digest((original_dir / 'ARTIFACT.md').read_bytes()))
                copy_input(original_dir / 'ARTIFACT.md', d, 'ROUND1_INVENTORY.md')
                inputs.append('ROUND1_INVENTORY.md')
                prior = next(k for k in reversed(starts) if k >= originals[-1][0]
                             and ends.get(k, {}).get('executed')
                             and ledger.evidence_available(ledger.recompute(
                                 repo, root / f'round-{k:04}', starts[k]), ends[k]))
                start['previous_round'] = prior
                copy_input(root / f'round-{prior:04}' / 'ARTIFACT.md', d, 'PREVIOUS_REVIEW.md')
                inputs.append('PREVIOUS_REVIEW.md')
                freeze(d / 'IMPLEMENTER_RESPONSE.md', response if response is not None else
                       b'No implementer response supplied. Inspect the complete remediation diff.\n')
                inputs.append('IMPLEMENTER_RESPONSE.md')
                freeze(d / 'REMEDIATION.patch', git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', r1head, head))
                freeze(d / 'REMEDIATION_CHANGED.txt', git(repo, 'diff', '--no-renames', '--name-only', r1head, head))
                freeze(d / 'REMEDIATION_HUNKS.md', hunk_markdown(hunks(repo, r1head, head)).encode())
                inputs += ['REMEDIATION.patch', 'REMEDIATION_CHANGED.txt', 'REMEDIATION_HUNKS.md']
            seal = run([SCRIPTS / 'target-seal.sh', 'seal', repo, base, head, d])
            require(seal.returncode == 0, 'target', seal.stderr.decode().strip())
            inputs += ['SEAL.txt', 'inventory.txt']
            freeze(d / 'DIFF.patch', git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', base, head))
            freeze(d / 'CHANGED.txt', git(repo, 'diff', '--no-renames', '--name-only', base, head))
            inputs += ['DIFF.patch', 'CHANGED.txt']
            values = {'REPOSITORY': os.environ.get('REVIEW_REPOSITORY_NAME') or str(repo), 'BASE_SHA': base,
                      'ATTEMPT_NUMBER': str(n), 'MAX_ROUNDS': str(MAX_ROUNDS),
                      'ROUND1_HEAD_SHA': head if phase == 1 else start['round1_head_sha'],
                      'ROUND2_HEAD_SHA': head, 'TRUSTED_INVENTORY_SHA256': start.get('inventory_sha256', ''),
                      'INVENTORY_INTEGRITY_RESULT': 'VERIFIED',
                      'REQUIREMENT_SOURCES_OR_NONE': os.environ.get('REVIEW_REQUIREMENTS', 'none'),
                      'KNOWN_ROUTED_OR_NONE': os.environ.get('REVIEW_ROUTED', 'none'),
                      'PROJECT_CLASS_CATALOG_OR_NONE': '\n\n'.join(filter(None, [
                          os.environ.get('REVIEW_CATALOG', 'none'), os.environ.get('REVIEW_HISTORY', '')])),
                      'FULL_SUITE_STATUS_OR_UNKNOWN': os.environ.get('REVIEW_SUITE_STATUS', 'UNKNOWN'),
                      'TOOL_NOTES_OR_NONE': os.environ.get('REVIEW_TOOL_NOTES', 'none')}
            rendered = run([sys.executable, SCRIPTS / 'lib/render-prompt.py', SKILL, phase,
                            *[f'{k}={v}' for k, v in values.items()]])
            require(rendered.returncode == 0, 'prompt', rendered.stderr.decode().strip())
            freeze(d / 'prompt.txt', rendered.stdout)
            inputs.append('prompt.txt')
            start.update(inputs=ledger.hashes(d, inputs), skill_sha256=protocol_sha256(SCRIPTS),
                         executor=executor)
            ledger.append(root, start)
            started = True
            # Clone locally so consumer .git and its shared worktrees remain untouched.
            # A short base, deliberately. macOS puts $TMPDIR at ~49 characters before this
            # prefix, and a unix socket path is capped at 104 bytes by sun_path -- measured: a
            # checkout at 81 characters pushed a project's `<stateDir>/hermes.mcp.sock` past the
            # limit and every socket test in the change failed there with ENOENT. The reviewer
            # then built its own short worktree to get the evidence, which is evidence produced
            # outside the seal, and that is worse than the failing tests. The path is still new
            # every round, so no standing trust accumulates.
            temp_base = Path('/private/tmp') if Path('/private/tmp').is_dir() else None
            clone = Path(tempfile.mkdtemp(prefix='r', dir=temp_base) if temp_base
                         else tempfile.mkdtemp(prefix='review-checkout-'))
            cp = run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', repo, clone])
            require(cp.returncode == 0, 'checkout', cp.stderr.decode().strip())
            require(run(['git', '-C', clone, 'checkout', '--quiet', '--detach', head]).returncode == 0,
                    'checkout', 'cannot check out sealed head')
            for name in inputs:
                if name in {'SEAL.txt', 'inventory.txt', 'prompt.txt'}:
                    continue
                require(not (clone / name).exists(), 'input-collision', f'repository already contains {name}')
                shutil.copyfile(d / name, clone / name)
            ledger.shell_guard('guard_no_seal_in_tree', clone)
            executor = start['executor']
            prompt = (d / 'prompt.txt').read_text()
            env = {k: v for k, v in os.environ.items() if not k.startswith('REVIEW_')}
            # Name the model, not only the executor. `executor codex` while REVIEW_CODEX_MODEL
            # selects another model reads as though the swap did not apply, and the swap is the
            # protocol's own remedy for a round that cannot close its artifact -- a consumer had
            # to verify by process identity that the model it asked for was the one running.
            model = (os.environ.get('REVIEW_CODEX_MODEL', 'executor default') if executor == 'codex'
                     else executor)
            print(f'review: round {n}, phase {phase}, head {head}, executor {executor} ({model})',
                  file=sys.stderr)
            if executor == 'stub':
                # Same guards and receipt, but never an eligible merge result.
                shutil.copyfile(os.environ['REVIEW_STUB'], d / 'events.jsonl')
                executed = True
                (d / 'executor.err').write_text('test fixture executor\n')
                rc = 0
            else:
                if executor == 'codex':
                    cmd = ['codex', 'exec', '--json', '-s', 'read-only']
                    if os.environ.get('REVIEW_CODEX_MODEL'):
                        cmd += ['-m', os.environ['REVIEW_CODEX_MODEL']]
                    cmd += [prompt]
                elif executor == 'claude':
                    # The checkout is deliberately NOT trusted, and the warning saying so is the
                    # property working. Its `.claude/settings.json` is a file from the tree under
                    # review, so a change can add `permissions.allow` entries to its own settings
                    # and a trusted checkout would hand them to the reviewer reviewing it. The path
                    # is new every round exactly so no standing trust accumulates, and pressing the
                    # dialog on the reviewer's behalf would grant a reviewed change the permissions
                    # it wrote for itself. Reported by a consumer as a possible defect; recorded so
                    # the next reader does not "fix" it.
                    cmd = ['claude', '-p', '--output-format', 'stream-json', '--verbose', prompt]
                else:
                    raise Rejected('GUARD FAIL [executor] use codex, claude, or stub')
                with (d / 'events.jsonl').open('wb') as out, (d / 'executor.err').open('wb') as err:
                    child = subprocess.Popen(cmd, cwd=clone, stdout=out, stderr=err,
                                             stdin=subprocess.DEVNULL, env=env, start_new_session=True)
                    executed = True
                    try:
                        rc = child.wait(timeout=timeout)
                    finally:
                        # A timeout, cancellation or exited parent must not leave its tool
                        # children writing into a checkout that is about to be removed.
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        child.wait()
            (d / 'executor-exit.txt').write_text(str(rc))
            (d / 'checkout-head.txt').write_bytes(git(clone, 'rev-parse', 'HEAD'))
            artifact = run([sys.executable, SCRIPTS / 'lib/extract.py', d / 'events.jsonl', '--final'])
            freeze(d / 'ARTIFACT.md', artifact.stdout)
            checks = ledger.recompute(repo, d, start, clone)
            recorded = all(c['ok'] for c in checks)
            fresh, freshness_reason = True, ''
            try:
                check_freshness()
            except (Rejected, OSError, ValueError, subprocess.SubprocessError) as e:
                fresh, freshness_reason = False, str(e).replace('\n', '; ')
            end = {'event': 'finished', 'round': n, 'executed': True, 'recorded': recorded,
                   'fresh_at_finish': fresh, 'freshness_reason': freshness_reason,
                   'guards': checks,
                   'inventory_sha256': digest(artifact.stdout) if phase == 1 else start['inventory_sha256'],
                   'outputs': ledger.hashes(d, ['ARTIFACT.md', 'events.jsonl', 'executor.err', 'executor-exit.txt', 'checkout-head.txt'])}
            ledger.append(root, end)
            finished = True
            for check in checks:
                if not check['ok']:
                    print(check['reason'], file=sys.stderr)
            print(f'review: {"RECORDED" if recorded else "FAILED"} {"FRESH" if fresh else "STALE"} artifact {d / "ARTIFACT.md"}; '
                  'maintainer must assess the evidence; no automatic merge approval')
            if not fresh:
                print(freshness_reason, file=sys.stderr)
            if n == MAX_ROUNDS:
                ledger.handoff(root, repo, head)
            return review_exit(recorded and fresh, n)
        except (Rejected, ledger.MissingGuard, OSError, ValueError, KeyError,
                subprocess.SubprocessError, KeyboardInterrupt) as e:
            reason = (f'executor timed out after {timeout:g}s' if isinstance(e, subprocess.TimeoutExpired)
                      else str(e).replace('\n', '; ') or 'review interrupted')
            if finished:
                print(reason, file=sys.stderr)
                return FAILED
            if child is not None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                (d / 'executor-exit.txt').write_text(str(child.returncode))
            if not started:
                start['inputs'] = ledger.hashes(d, inputs)
                ledger.append(root, start)
            output_names = [name for name in ['ARTIFACT.md', 'events.jsonl', 'executor.err',
                            'executor-exit.txt', 'checkout-head.txt'] if (d / name).is_file()]
            ledger.append(root, {'event': 'finished', 'round': n, 'executed': executed,
                                 'recorded': False, 'reason': reason,
                                 'outputs': ledger.hashes(d, output_names)})
            print(reason, file=sys.stderr)
            if n == MAX_ROUNDS:
                ledger.handoff(root, repo, head)
            return FAILED
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
            if clone:
                shutil.rmtree(clone)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        sys.exit(str(e).replace('\n', '; '))
