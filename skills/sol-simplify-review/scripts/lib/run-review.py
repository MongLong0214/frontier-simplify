#!/usr/bin/env python3
"""Trusted host: freeze inputs, run one reviewer, recompute guards, append a receipt."""
import argparse
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from protocol import (Rejected, require, git, digest, fields, section, axes, verdict,
                      check_response, escape_ids, hunks, hunk_markdown, blocks, check_extra_round)
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


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['1', '2', 'report', 'path', 'hunks'])
    p.add_argument('repo', type=Path)
    p.add_argument('head', help='commit/ref; ignored for report/path')
    p.add_argument('pr', help='stable PR ID; actual round is assigned by the host')
    p.add_argument('base', nargs='?', default='')
    p.add_argument('executor', nargs='?', default='')
    a = p.parse_args()
    repo = a.repo.resolve()
    root = root_for(repo, a.pr)
    if a.phase == 'path':
        print(root)
        return 0
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if a.phase == 'report':
            ledger.report(root, repo)
            return 0
        starts, ends, originals = ledger.audit(root, repo)
        head = git(repo, 'rev-parse', '--verify', a.head + '^{commit}').decode().strip()
        if a.phase == 'hunks':
            require(originals, 'handoff', 'no accepted round-1 inventory for this PR')
            print(hunk_markdown(hunks(repo, originals[-1][2]['head_sha'], head)), end='')
            return 0
        phase = int(a.phase)
        n = len(starts) + 1
        d = root / f'round-{n:04}'
        d.mkdir()
        inputs = []
        start = {'event': 'started', 'round': n, 'phase': phase, 'head_sha': head,
                 'repo': str(repo), 'pr': a.pr, 'expected_ids': [], 'inputs': {}}
        started = False
        executed = False
        clone = None
        try:
            if a.base:
                base = git(repo, 'rev-parse', '--verify', a.base + '^{commit}').decode().strip()
            elif phase == 2 and originals:
                base = originals[-1][2]['base_sha']
            else:
                target = os.environ.get('REVIEW_TARGET_BRANCH', '')
                require(target, 'base', 'provide merge-base or REVIEW_TARGET_BRANCH; current branch is not a target default')
                base = git(repo, 'merge-base', target, head).decode().strip()
            start['base_sha'] = base
            require(run(['git', '-C', repo, 'merge-base', '--is-ancestor', base, head]).returncode == 0,
                    'ancestry', 'base is not an ancestor of head')
            if n >= 3 or (phase == 1 and originals):
                require(originals, 'round-budget', 'cannot name escapes without a sealed round-1 inventory')
                path = os.environ.get('REVIEW_ESCAPES', '')
                require(path, 'round-budget', 'round 3+ or scope restart requires REVIEW_ESCAPES naming original item IDs and evidence')
                copy_input(path, d, 'ESCAPES.md')
                inputs.append('ESCAPES.md')
                last = max(starts)
                prior_end = ends.get(last, {})
                prior_file = root / f'round-{last:04}' / 'ARTIFACT.md'
                # A preflight rejection does not erase the last review's open items.
                prior_review = max((k for k, e in ends.items() if e.get('executed')), default=last)
                prior_file = root / f'round-{prior_review:04}' / 'ARTIFACT.md'
                prior_escape = prior_file.parent / 'ESCAPES.md'
                check_extra_round((d / 'ESCAPES.md').read_text(), originals[0][3],
                                  prior_file.read_text() if prior_file.exists() else '',
                                  starts[prior_review]['phase'], prior_end.get('accepted', False),
                                  head != starts[prior_review]['head_sha'],
                                  prior_escape.read_text() if prior_escape.exists() else '')
            if phase == 2:
                require(originals, 'handoff', 'round 2 requires an accepted sealed round-1 inventory')
                _, original_dir, original_start, inventory = originals[-1]
                require(axes(inventory).get('enumeration') == 'COMPLETE', 'enumeration', 'RESTART_ROUND_1: enumeration was INCOMPLETE')
                require(base == original_start['base_sha'], 'scope-change', 'RESTART_ROUND_1: base changed')
                r1head = original_start['head_sha']
                require(run(['git', '-C', repo, 'merge-base', '--is-ancestor', r1head, head]).returncode == 0,
                        'ancestry', 'RESTART_ROUND_1: remediation does not descend from round 1')
                start.update(round1_head_sha=r1head, inventory_sha256=digest((original_dir / 'ARTIFACT.md').read_bytes()))
                copy_input(original_dir / 'ARTIFACT.md', d, 'ROUND1_INVENTORY.md')
                inputs.append('ROUND1_INVENTORY.md')
                response = os.environ.get('REVIEW_RESPONSE', '')
                require(response, 'response', 'set REVIEW_RESPONSE to the separate implementer response')
                copy_input(response, d, 'IMPLEMENTER_RESPONSE.md')
                inputs.append('IMPLEMENTER_RESPONSE.md')
                unrelated = check_response((d / 'IMPLEMENTER_RESPONSE.md').read_text(), inventory, repo, r1head, head, start['inventory_sha256'])
                require(not unrelated, 'scope-change', 'RESTART_ROUND_1: unrelated changes at ' + ', '.join(unrelated))
                freeze(d / 'REMEDIATION.patch', git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', r1head, head))
                freeze(d / 'REMEDIATION_CHANGED.txt', git(repo, 'diff', '--no-renames', '--name-only', r1head, head))
                freeze(d / 'REMEDIATION_HUNKS.md', hunk_markdown(hunks(repo, r1head, head)).encode())
                inputs += ['REMEDIATION.patch', 'REMEDIATION_CHANGED.txt', 'REMEDIATION_HUNKS.md']
            else:
                require(os.environ.get('REVIEW_CATALOG', '').strip().lower() in {'', 'none'} or os.environ.get('REVIEW_EXPECTED_IDS'),
                        'enumeration', 'supplied catalog needs REVIEW_EXPECTED_IDS (P-01,...)')
                start['expected_ids'] = list(filter(None, os.environ.get('REVIEW_EXPECTED_IDS', '').split(',')))
            seal = run([SCRIPTS / 'target-seal.sh', 'seal', repo, base, head, d])
            require(seal.returncode == 0, 'target', seal.stderr.decode().strip())
            inputs += ['SEAL.txt', 'inventory.txt']
            freeze(d / 'DIFF.patch', git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames', '--binary', base, head))
            freeze(d / 'CHANGED.txt', git(repo, 'diff', '--no-renames', '--name-only', base, head))
            inputs += ['DIFF.patch', 'CHANGED.txt']
            values = {'REPOSITORY': str(repo), 'BASE_SHA': base,
                      'ROUND1_HEAD_SHA': head if phase == 1 else start['round1_head_sha'],
                      'ROUND2_HEAD_SHA': head, 'TRUSTED_INVENTORY_SHA256': start.get('inventory_sha256', ''),
                      'INVENTORY_INTEGRITY_RESULT': 'VERIFIED',
                      'REQUIREMENT_SOURCES_OR_NONE': os.environ.get('REVIEW_REQUIREMENTS', 'none'),
                      'KNOWN_ROUTED_OR_NONE': os.environ.get('REVIEW_ROUTED', 'none'),
                      'PROJECT_CLASS_CATALOG_OR_NONE': os.environ.get('REVIEW_CATALOG', 'none'),
                      'FULL_SUITE_STATUS_OR_UNKNOWN': os.environ.get('REVIEW_SUITE_STATUS', 'UNKNOWN'),
                      'TOOL_NOTES_OR_NONE': os.environ.get('REVIEW_TOOL_NOTES', 'none')}
            rendered = run([sys.executable, SCRIPTS / 'lib/render-prompt.py', SKILL, phase,
                            *[f'{k}={v}' for k, v in values.items()]])
            require(rendered.returncode == 0, 'prompt', rendered.stderr.decode().strip())
            freeze(d / 'prompt.txt', rendered.stdout)
            inputs.append('prompt.txt')
            start.update(inputs=ledger.hashes(d, inputs), skill_sha256=digest(SKILL.read_bytes()),
                         executor=a.executor or os.environ.get('REVIEW_EXECUTOR', 'codex'))
            ledger.append(root, start)
            started = True
            # Clone locally so consumer .git and its shared worktrees remain untouched.
            clone = Path(tempfile.mkdtemp(prefix='review-checkout-'))
            cp = run(['git', 'clone', '--quiet', '--no-hardlinks', '--no-checkout', repo, clone])
            require(cp.returncode == 0, 'checkout', cp.stderr.decode().strip())
            require(run(['git', '-C', clone, 'checkout', '--quiet', '--detach', head]).returncode == 0,
                    'checkout', 'cannot check out sealed head')
            for name in inputs:
                if name in {'SEAL.txt', 'inventory.txt', 'ESCAPES.md', 'prompt.txt'}:
                    continue
                require(not (clone / name).exists(), 'input-collision', f'repository already contains {name}')
                shutil.copyfile(d / name, clone / name)
            ledger.shell_guard('guard_no_seal_in_tree', clone)
            executor = start['executor']
            prompt = (d / 'prompt.txt').read_text()
            env = {k: v for k, v in os.environ.items() if not k.startswith('REVIEW_')}
            print(f'review: round {n}, phase {phase}, head {head}, executor {executor}', file=sys.stderr)
            executed = True
            if executor == 'stub':
                # Same guards and receipt, but never an eligible merge result.
                shutil.copyfile(os.environ['REVIEW_STUB'], d / 'events.jsonl')
                (d / 'executor.err').write_text('test fixture executor\n')
                rc = 0
            else:
                if executor == 'codex':
                    cmd = ['codex', 'exec', '--json', '-s', 'read-only']
                    if os.environ.get('REVIEW_CODEX_MODEL'):
                        cmd += ['-m', os.environ['REVIEW_CODEX_MODEL']]
                    cmd += [prompt]
                elif executor == 'claude':
                    cmd = ['claude', '-p', '--output-format', 'stream-json', '--verbose', prompt]
                else:
                    raise Rejected('GUARD FAIL [executor] use codex, claude, or stub')
                with (d / 'events.jsonl').open('wb') as out, (d / 'executor.err').open('wb') as err:
                    rc = subprocess.run(cmd, cwd=clone, stdout=out, stderr=err, stdin=subprocess.DEVNULL, env=env).returncode
            (d / 'executor-exit.txt').write_text(str(rc))
            (d / 'checkout-head.txt').write_bytes(git(clone, 'rev-parse', 'HEAD'))
            marker = '# Round 1 review inventory' if phase == 1 else '# Round 2 closure review'
            artifact = run([sys.executable, SCRIPTS / 'lib/extract.py', d / 'events.jsonl', marker])
            freeze(d / 'ARTIFACT.md', artifact.stdout)
            checks = ledger.recompute(repo, d, start, clone)
            accepted = all(c['ok'] for c in checks)
            text = artifact.stdout.decode()
            stats = ledger.statistics(text, phase)
            end = {'event': 'finished', 'round': n, 'executed': True, 'accepted': accepted,
                   'guards': checks, **stats,
                   'inventory_sha256': digest(artifact.stdout) if phase == 1 else start['inventory_sha256'],
                   'outputs': ledger.hashes(d, ['ARTIFACT.md', 'events.jsonl', 'executor.err', 'executor-exit.txt', 'checkout-head.txt'])}
            ledger.append(root, end)
            for check in checks:
                if not check['ok']:
                    print(check['reason'], file=sys.stderr)
            print(f'review: {"ACCEPTED" if accepted else "REJECTED"} artifact {d / "ARTIFACT.md"}; verdict {verdict(text) or "unknown"}')
            # A valid BLOCK inventory is an accepted handoff, not permission to merge.
            fixture_chain = executor == 'stub' or any(s.get('executor') == 'stub' for s in starts.values())
            return 0 if accepted and verdict(text) in {'PASS', 'PASS WITH NITS'} and not fixture_chain else 5
        except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
            reason = str(e).replace('\n', '; ')
            if not started:
                start['inputs'] = ledger.hashes(d, inputs)
                ledger.append(root, start)
            ledger.append(root, {'event': 'finished', 'round': n, 'executed': False,
                                 'accepted': False, 'reason': reason, 'outputs': {}})
            print(reason, file=sys.stderr)
            return 5
        finally:
            if clone:
                shutil.rmtree(clone)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Rejected, OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        sys.exit(str(e).replace('\n', '; '))
