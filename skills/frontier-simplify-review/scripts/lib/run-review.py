#!/usr/bin/env python3
"""Trusted host: freeze inputs, run one reviewer, recompute guards, append a receipt."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from datetime import datetime, timezone

from protocol import (Rejected, require, git, digest, hunks, hunk_markdown, artifact_root,
                      review_context, review_exit, RECORDED, FAILED, HANDOFF, MAX_ROUNDS,
                      child_environment, REDESIGN_REQUIRED, WITNESS_FAILING)
import evidence
import followup
import ledger
from scope import build_scope, scope_bytes

SCRIPTS = Path(__file__).resolve().parent.parent
SKILL = SCRIPTS.parent / 'SKILL.md'


def run(args, cwd=None, stdout=subprocess.PIPE, input=None):
    return subprocess.run(list(map(str, args)), cwd=cwd, stdout=stdout,
                          stderr=subprocess.PIPE, env=child_environment(), input=input)


def root_for(repo, pr):
    require(bool(pr) and all(c.isalnum() or c in '-_.' for c in pr) and pr not in {'.', '..'},
            'pr-id', 'use one stable PR number or local review ID, never a round suffix')
    common = git(repo, 'rev-parse', '--git-common-dir').decode().strip()
    identity = str((Path(repo) / common).resolve())
    root = artifact_root()
    require(not root.is_relative_to(Path(repo).resolve()), 'host-location', 'REVIEW_ARTIFACTS must be outside the consumer checkout')
    return root / digest(identity.encode())[:16] / pr


def freeze(path, data):
    with path.open('xb') as f:
        f.write(data)


def copy_input(source, directory, name):
    require(Path(name).name == name and name not in {'.', '..'}, 'input-collision',
            'input name must be top-level')
    try:
        freeze(directory / name, Path(source).read_bytes())
    except (FileExistsError, IsADirectoryError):
        require(False, 'input-collision', f'repository already contains {name}')


def observe_checkout(clone, head, directory, installed, expected_hashes):
    """Measure only the owned primary checkout, before it is removed."""
    if clone.is_symlink() or not clone.is_dir():
        return {name: {'status': 'error', 'reason': 'primary checkout is unavailable'}
                for name in ('head', 'tracked', 'input_copies')}
    observations = {}
    try:
        result = run(['git', '-C', clone, 'rev-parse', '--verify', 'HEAD^{commit}'])
        if result.returncode:
            observations['head'] = {'status': 'error', 'reason': f'HEAD check exited {result.returncode}'}
        else:
            actual = result.stdout.decode().strip()
            observations['head'] = ({'status': 'unchanged', 'observed_sha': actual} if actual == head
                                    else {'status': 'changed', 'observed_sha': actual,
                                          'reason': 'checkout HEAD differs from the sealed head'})
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        observations['head'] = {'status': 'error', 'reason': type(error).__name__}

    checks = [('index', ['git', '-C', clone, 'diff', '--cached', '--quiet', '--no-ext-diff',
                         '--no-textconv', '--no-renames', 'HEAD', '--']),
              ('worktree', ['git', '-C', clone, 'diff', '--quiet', '--no-ext-diff',
                            '--no-textconv', '--no-renames', '--'])]
    observations['tracked'] = {'status': 'unchanged'}
    for label, command in checks:
        try:
            result = run(command)
            if result.returncode == 1:
                observations['tracked'] = {'status': 'changed', 'reason': f'tracked {label} differs'}
                break
            if result.returncode:
                observations['tracked'] = {'status': 'error',
                                           'reason': f'tracked {label} check exited {result.returncode}'}
                break
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            observations['tracked'] = {'status': 'error', 'reason': type(error).__name__}
            break

    observations['input_copies'] = {'status': 'unchanged'}
    if not clone.is_dir():
        observations['input_copies'] = {'status': 'error', 'reason': 'primary checkout is unavailable'}
    else:
        for name in installed:
            source, target = directory / name, clone / name
            try:
                if target.is_symlink() or not target.is_file():
                    observations['input_copies'] = {'status': 'changed', 'reason': f'{name} is missing or not regular'}
                    break
                expected = source.read_bytes()
                if digest(expected) != expected_hashes[name]:
                    observations['input_copies'] = {'status': 'error', 'reason': f'{name} host input changed'}
                    break
                if target.stat().st_size != len(expected) or target.read_bytes() != expected:
                    observations['input_copies'] = {'status': 'changed', 'reason': f'{name} bytes changed'}
                    break
            except (OSError, ValueError, KeyError) as error:
                observations['input_copies'] = {'status': 'error', 'reason': f'{name}: {type(error).__name__}'}
                break
    return observations


def witness_timeout():
    timeout = float(os.environ.get('REVIEW_WITNESS_TIMEOUT', '300'))
    require(math.isfinite(timeout) and timeout > 0, 'witness-timeout',
            'REVIEW_WITNESS_TIMEOUT must be positive finite seconds')
    return timeout


def run_witnesses(root, repo, head, starts, ends, originals):
    """Rerun the sequence's preserved witnesses on `head`: (rows, witnesses, overlay, logs)."""
    if not originals:
        return [], {}, {}, None
    witnesses, overlay = evidence.view(root, starts, ends, originals[-1][0])
    disputed = {w.strip() for w in os.environ.get('REVIEW_WITNESS_DISPUTED', '').split(',') if w.strip()}
    logs = root / 'witness-runs' / f'{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")}-{head[:12]}'
    rows = evidence.precheck(repo, head, witnesses, overlay, logs, witness_timeout(), disputed)
    for wid in sorted(disputed - {row['id'] for row in rows}):
        print(f'review: REVIEW_WITNESS_DISPUTED names {wid}, which is not an active witness', file=sys.stderr)
    return rows, witnesses, overlay, logs if rows else None


def main(argv=None, freshness_check=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['1', '2', 'auto', 'status', 'report', 'path', 'hunks', 'witnesses'])
    p.add_argument('repo', type=Path)
    p.add_argument('head', help='commit/ref; ignored for report/path')
    p.add_argument('pr', help='stable PR ID; actual round is assigned by the host')
    p.add_argument('base', nargs='?', default='')
    p.add_argument('executor', nargs='?', default='')
    p.add_argument('--supplementary', action='store_true',
                   help='review beyond the automatic attempts, under an explicit recorded grant')
    p.add_argument('--granted-by', default='', help='who granted the supplementary budget')
    p.add_argument('--budget', type=int, help='supplementary reviews granted for this PR in total')
    a = p.parse_args(argv)
    if a.supplementary and (not a.granted_by.strip() or a.budget is None or a.budget < 1
                            or a.phase not in {'1', '2', 'auto'}):
        p.error('--supplementary needs a review phase, --granted-by and a positive --budget')
    if not a.supplementary and (a.granted_by or a.budget is not None):
        p.error('--granted-by and --budget apply only with --supplementary')
    grant = {'granted_by': a.granted_by.strip(), 'budget': a.budget} if a.supplementary else None
    repo = a.repo.resolve()
    root = root_for(repo, a.pr)
    if a.phase == 'path':
        print(root)
        return 0
    executor = a.executor or os.environ.get('REVIEW_EXECUTOR', 'codex')
    def caller_inputs():
        source = os.environ.get('REVIEW_RESPONSE')
        response = Path(source).read_bytes() if source else None
        source = os.environ.get('REVIEW_REDESIGN')
        redesign = Path(source).read_bytes() if source else None
        context = review_context(SCRIPTS, executor, response, redesign)
        if os.environ.get('REVIEW_TARGET_BRANCH') and not os.environ.get('REVIEW_TARGET_OID'):
            context['target_sha'] = git(repo, 'rev-parse', '--verify',
                                        os.environ['REVIEW_TARGET_BRANCH'] + '^{commit}').decode().strip()
        return context, response, redesign
    if a.phase == 'status':
        head = git(repo, 'rev-parse', '--verify', a.head + '^{commit}').decode().strip()
        base = git(repo, 'rev-parse', '--verify', a.base + '^{commit}').decode().strip() if a.base else None
        ledger.status(root, repo, head, base, caller_inputs()[0])
        return 0
    if a.phase == 'witnesses':
        # The implementer's own preflight: the same rerun a follow-up starts with, and no model.
        head = git(repo, 'rev-parse', '--verify', a.head + '^{commit}').decode().strip()
        starts, ends, originals = ledger.audit(root, repo)
        rows, witnesses, _, logs = run_witnesses(root, repo, head, starts, ends, originals)
        print(evidence.results_markdown(head, rows, witnesses, logs), end='')
        return WITNESS_FAILING if evidence.blocking(rows) else 0
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
        orphans = ledger.orphaned_rounds(root, starts)
        require(not orphans, 'orphaned-preparation',
                f'unledgered round path already exists: {orphans[0] if orphans else ""}')
        head = git(repo, 'rev-parse', '--verify', a.head + '^{commit}').decode().strip()
        automatic, supplementary, _ = ledger.budget(starts)
        print('review: ' + ledger.cumulative(root, starts, grant), file=sys.stderr)
        stop_reason = (f"the supplementary budget of {grant['budget']} granted by {grant['granted_by']} "
                       'is spent' if grant else 'automatic review has stopped')
        if grant:
            require(automatic >= MAX_ROUNDS, 'supplementary',
                    f'{MAX_ROUNDS - automatic} automatic attempt(s) remain; a supplementary grant starts after them')
        if (supplementary >= grant['budget']) if grant else (len(starts) >= MAX_ROUNDS):
            ledger.handoff(root, repo, head, stop_reason)
            return HANDOFF
        context, response, redesign = caller_inputs()
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
            available = (bool(end.get('recorded', end.get('accepted')))
                         and ledger.evidence_available(ledger.recompute(
                             repo, root / f"round-{latest['round']:04}", latest), end, latest))
            return review_exit(available and end.get('fresh_at_finish', True),
                               *((supplementary, grant['budget']) if grant else (len(starts),)))

        # Both stops come before a reservation: they launch no reviewer and use no attempt.
        reviews = followup.recorded(root, starts, ends)
        tracked = followup.tracked(reviews)
        keys = followup.recurring(reviews) if phase == 2 else []
        if keys:
            latest_review = starts[reviews[-1][0]]
            reviewed = (latest_review.get('inputs', {}).get('IMPLEMENTER_REDESIGN.md')
                        if latest_review.get('redesign_supplied') else None)
            if redesign is None or digest(redesign) == reviewed:
                path = followup.redesign_request(root, keys, tracked)
                print(f'review: REDESIGN_REQUIRED {", ".join(keys)} stayed open in two consecutive '
                      'reviews' + (' and the supplied redesign was already reviewed' if redesign else '')
                      + '; no reviewer launched and no attempt used. Answer the template in '
                      f'{path} and supply it as REVIEW_REDESIGN.', file=sys.stderr)
                return REDESIGN_REQUIRED
        witness_rows, witnesses, overlay = [], {}, {}
        if phase == 2:
            witness_rows, witnesses, overlay, logs = run_witnesses(root, repo, head, starts, ends, originals)
            failing = evidence.blocking(witness_rows)
            if failing:
                print(evidence.results_markdown(head, witness_rows, witnesses, logs), end='')
                print(f'review: WITNESS_FAILING {", ".join(failing)} on {head}: the repair is unfinished; '
                      'no reviewer launched and no attempt used. If a witness itself is wrong, name it in '
                      'REVIEW_WITNESS_DISPUTED and the reviewer will judge it.', file=sys.stderr)
                return WITNESS_FAILING
        notes = []
        if phase == 2 and reviews:
            latest_round = reviews[-1][0]
            repair = run(['git', '-C', repo, 'diff', '--no-color', '--no-ext-diff', '--no-textconv',
                          '--no-renames', starts[latest_round]['head_sha'], head])
            warning = repair.returncode == 0 and followup.shape_warning(tracked, latest_round, repair.stdout)
            if warning:
                notes.append(warning)
        if response is not None:
            missing = followup.unreceipted(response.decode('utf-8', 'replace'),
                                           followup.executed_texts(root, ends))
            if missing:
                notes.append('IMPLEMENTER_RESPONSE.md cites finding IDs that no review recorded for this '
                             f'PR contains: {", ".join(missing)}. A review run outside this runner has no '
                             'receipt, budget or handoff here; weigh those citations as the implementer\'s account.')
        for note in notes:
            print('review: ' + note, file=sys.stderr)

        n = len(starts) + 1
        last = (supplementary + 1 >= grant['budget']) if grant else (n >= MAX_ROUNDS)
        d = root / f'round-{n:04}'
        inputs = []
        start = {'event': 'started', 'round': n, 'phase': phase, 'head_sha': head,
                 'base_sha': base, 'repo': str(repo), 'pr': a.pr, 'mode': ledger.MODE,
                 'inputs': {}, 'context': context, 'executor': executor,
                 'skill_sha256': context['protocol_sha256'], 'checkout_checks_version': 1}
        if grant:
            start['supplementary'] = dict(grant, number=supplementary + 1)
        if redesign is not None and phase == 2:
            start['redesign_supplied'] = True
        started = False
        executed = False
        finished = False
        clone = None
        installed = []
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
                inventory_bytes = (original_dir / 'ARTIFACT.md').read_bytes()
                prior = next(k for k in reversed(starts) if k >= originals[-1][0]
                             and ends.get(k, {}).get('executed')
                             and ledger.evidence_available(ledger.recompute(
                                 repo, root / f'round-{k:04}', starts[k]), ends[k], starts[k]))
                previous_bytes = (root / f'round-{prior:04}' / 'ARTIFACT.md').read_bytes()
                start.update(original_round=originals[-1][0], round1_head_sha=r1head,
                             inventory_sha256=digest(inventory_bytes),
                             previous_round=prior)
            scope = build_scope(repo, base if phase == 1 else r1head, head,
                                'change' if phase == 1 else 'remediation')
            require(phase == 2 or bool(scope['files']), 'empty-target',
                    'phase 1 requires a nonempty Base..Reviewed-head change')
            frozen_scope = scope_bytes(scope)
            start['scope_schema_version'] = 1
            require(not d.exists() and not d.is_symlink(), 'orphaned-preparation',
                    f'unledgered round directory already exists: {d}')
            ledger.append(root, start)
            started = True
            d.mkdir()
            freeze(d / 'SCOPE.json', frozen_scope)
            inputs.append('SCOPE.json')
            if phase == 2:
                freeze(d / 'ROUND1_INVENTORY.md', inventory_bytes)
                inputs.append('ROUND1_INVENTORY.md')
                freeze(d / 'PREVIOUS_REVIEW.md', previous_bytes)
                inputs.append('PREVIOUS_REVIEW.md')
                freeze(d / 'IMPLEMENTER_RESPONSE.md', response if response is not None else
                       b'No implementer response supplied. Inspect the complete remediation diff.\n')
                inputs.append('IMPLEMENTER_RESPONSE.md')
                freeze(d / 'IMPLEMENTER_REDESIGN.md', redesign if redesign is not None else
                       b'No redesign supplied.\n')
                freeze(d / 'WITNESS_RESULTS.md',
                       evidence.results_markdown(head, witness_rows, witnesses).encode())
                inputs += ['IMPLEMENTER_REDESIGN.md', 'WITNESS_RESULTS.md']
                freeze(d / 'REMEDIATION.patch', git(repo, 'diff', '--no-color', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', r1head, head))
                freeze(d / 'REMEDIATION_CHANGED.txt', git(repo, 'diff', '--no-renames', '--name-only', r1head, head))
                freeze(d / 'REMEDIATION_HUNKS.md', hunk_markdown(hunks(repo, r1head, head)).encode())
                inputs += ['REMEDIATION.patch', 'REMEDIATION_CHANGED.txt', 'REMEDIATION_HUNKS.md']
            seal = run([SCRIPTS / 'target-seal.sh', 'seal', repo, base, head, d])
            require(seal.returncode == 0, 'target', seal.stderr.decode().strip())
            with (d / 'SEAL.txt').open('a') as seal_file:
                seal_file.write(f'protocol_sha256: {start["skill_sha256"]}\n')
            inputs += ['SEAL.txt', 'inventory.txt']
            freeze(d / 'DIFF.patch', git(repo, 'diff', '--no-color', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', base, head))
            freeze(d / 'CHANGED.txt', git(repo, 'diff', '--no-renames', '--name-only', base, head))
            inputs += ['DIFF.patch', 'CHANGED.txt']
            budget = (f"supplementary review {supplementary + 1} of {grant['budget']} granted by "
                      f"{grant['granted_by']}, after {automatic} automatic attempts" if grant
                      else f'automatic attempt {n} of {MAX_ROUNDS}')
            values = {'REPOSITORY': os.environ.get('REVIEW_REPOSITORY_NAME') or str(repo), 'BASE_SHA': base,
                      'REVIEW_BUDGET': budget, 'OPEN_INVARIANTS_OR_NONE': followup.carried(tracked),
                      'HOST_NOTES_OR_NONE': '\n' + '\n'.join('- ' + note for note in notes) if notes else 'none',
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
                            '--values-stdin'], input=json.dumps(values, ensure_ascii=False).encode('utf-8'))
            require(rendered.returncode == 0, 'prompt', rendered.stderr.decode().strip())
            freeze(d / 'prompt.txt', rendered.stdout)
            inputs.append('prompt.txt')
            prepared_inputs = ledger.hashes(d, inputs)
            ledger.append(root, {'event': 'prepared', 'round': n, 'inputs': prepared_inputs})
            start['inputs'] = prepared_inputs
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
                copy_input(d / name, clone, name)
                installed.append(name)
            witness_installed, witness_notes = evidence.prepare(clone, overlay if phase == 2 else {})
            for note in witness_notes:
                print('review: ' + note, file=sys.stderr)
            executor = start['executor']
            env = {k: v for k, v in child_environment().items() if not k.startswith('REVIEW_')}
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
                if os.environ.get('REVIEW_STUB_EVIDENCE') and witness_installed is not None:
                    # Stands in for a reviewer writing its reproductions.
                    shutil.copytree(os.environ['REVIEW_STUB_EVIDENCE'], clone / evidence.EVIDENCE,
                                    dirs_exist_ok=True)
                executed = True
                (d / 'executor.err').write_text('test fixture executor\n')
                rc = 0
            else:
                if executor == 'codex':
                    cmd = ['codex', 'exec', '--json', '-s', 'read-only']
                    if os.environ.get('REVIEW_CODEX_MODEL'):
                        cmd += ['-m', os.environ['REVIEW_CODEX_MODEL']]
                    cmd += ['-']
                elif executor == 'claude':
                    # The checkout is deliberately NOT trusted, and the warning saying so is the
                    # property working. Its `.claude/settings.json` is a file from the tree under
                    # review, so a change can add `permissions.allow` entries to its own settings
                    # and a trusted checkout would hand them to the reviewer reviewing it. The path
                    # is new every round exactly so no standing trust accumulates, and pressing the
                    # dialog on the reviewer's behalf would grant a reviewed change the permissions
                    # it wrote for itself. Reported by a consumer as a possible defect; recorded so
                    # the next reader does not "fix" it.
                    cmd = ['claude', '-p', '--input-format', 'text',
                           '--output-format', 'stream-json', '--verbose']
                else:
                    raise Rejected('GUARD FAIL [executor] use codex, claude, or stub')
                with (d / 'events.jsonl').open('wb') as out, (d / 'executor.err').open('wb') as err, \
                     (d / 'prompt.txt').open('rb') as prompt_file:
                    child = subprocess.Popen(cmd, cwd=clone, stdout=out, stderr=err,
                                             stdin=prompt_file, env=env, start_new_session=True)
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
            observations = observe_checkout(clone, head, d, installed, start['inputs'])
            (d / 'checkout-head.txt').write_text(observations['head'].get('observed_sha', '') + '\n')
            try:
                witnessed = evidence.collect(clone, d, witness_installed)
            except (Rejected, OSError, ValueError) as e:
                # Losing a reproduction is worth saying, not worth discarding the review over.
                witnessed = False
                print(f'review: witnesses not preserved: {e}', file=sys.stderr)
            artifact = run([sys.executable, SCRIPTS / 'lib/extract.py', d / 'events.jsonl', '--final'])
            freeze(d / 'ARTIFACT.md', artifact.stdout)
            checks = ledger.recompute(repo, d, start, clone)
            recorded = all(c['ok'] for c in checks) and ledger.observations_state(start, {
                'executed': True, 'checkout_observations': observations}) == 'UNCHANGED'
            fresh, freshness_reason = True, ''
            try:
                check_freshness()
            except (Rejected, OSError, ValueError, subprocess.SubprocessError) as e:
                fresh, freshness_reason = False, str(e).replace('\n', '; ')
            end = {'event': 'finished', 'round': n, 'executed': True, 'recorded': recorded,
                   'fresh_at_finish': fresh, 'freshness_reason': freshness_reason,
                   'guards': checks, 'checkout_observations': observations,
                   'inventory_sha256': digest(artifact.stdout) if phase == 1 else start['inventory_sha256'],
                   'outputs': ledger.hashes(d, ['ARTIFACT.md', 'events.jsonl', 'executor.err', 'executor-exit.txt', 'checkout-head.txt']
                                            + (['WITNESSES.json'] if witnessed else []))}
            ledger.append(root, end)
            finished = True
            for check in checks:
                if not check['ok']:
                    print(check['reason'], file=sys.stderr)
            print(f'review: {"RECORDED" if recorded else "FAILED"} {"FRESH" if fresh else "STALE"} artifact {d / "ARTIFACT.md"}; '
                  'maintainer must assess the evidence; no automatic merge approval')
            print('review: ' + ledger.cumulative(root, {**starts, n: start}, grant), file=sys.stderr)
            if not fresh:
                print(freshness_reason, file=sys.stderr)
            if last:
                ledger.handoff(root, repo, head, stop_reason)
            return FAILED if not (recorded and fresh) else HANDOFF if last else RECORDED
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
                print(reason, file=sys.stderr)
                return FAILED
            observations = (observe_checkout(clone, head, d, installed, start['inputs'])
                            if executed else None)
            output_names = [name for name in ['ARTIFACT.md', 'events.jsonl', 'executor.err',
                            'executor-exit.txt', 'checkout-head.txt'] if (d / name).is_file()]
            end = {'event': 'finished', 'round': n, 'executed': executed,
                   'recorded': False, 'reason': reason, 'outputs': ledger.hashes(d, output_names)}
            if executed:
                end['checkout_observations'] = observations
            ledger.append(root, end)
            print(reason, file=sys.stderr)
            if last:
                ledger.handoff(root, repo, head, stop_reason)
            return FAILED
        finally:
            for sig, handler in old_handlers.items():
                signal.signal(sig, handler)
            if clone:
                if clone.is_symlink():
                    clone.unlink()
                elif clone.exists():
                    shutil.rmtree(clone)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        print(str(e).replace('\n', '; '), file=sys.stderr)
        sys.exit(FAILED)
