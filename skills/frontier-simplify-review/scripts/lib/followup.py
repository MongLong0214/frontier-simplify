"""What one review hands the next: open contract invariants, redesign requests and the handoff.

The reviewer's prose stays the evidence. A few explicit lines are read from it only to stop
work -- to ask for a redesign instead of another review -- never to close a finding or
authorize a merge. A review without those lines reports nothing here, which is not the same
as nothing open.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from protocol import require, child_environment
import evidence
import ledger

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent.parent / 'SKILL.md'
INVARIANT = re.compile(r'^[ \t]*[-*][ \t]+invariant:[ \t]*(.+?)[ \t]*$', re.M)
KEY = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}')
FAMILY = re.compile(r'(?:family[ \t]*)?([0-9]{1,2}(?:[ \t]*,[ \t]*[0-9]{1,2})*)', re.I)
STATUSES = {'OPEN', 'CLOSED', 'ROUND1-ESCAPE', 'REGRESSION', 'DISPUTED', 'UNVERIFIABLE'}
RECURRING = {'OPEN', 'ROUND1-ESCAPE', 'REGRESSION'}
# Conditionals and early exits: the shape of a repair that removes one path at a time.
BRANCH = re.compile(r'^(?:[})\]]\s*)?(?:if|elif|else|unless|when|case|switch|guard|match|except|catch)\b'
                    r'|^(?:return|continue|break|raise|throw)\b|\bif\b.+\belse\b')
COMMENT = ('#', '//', '/*', '*', '--', '<!--')
TEST_PATH = re.compile(r'(^|/)(tests?|__tests__|spec|specs)/|(^|/)test_[^/]+$|[._-](test|spec)\.[^/]+$')
PROSE_SUFFIXES = {'.md', '.txt', '.rst', '.json', '.yml', '.yaml', '.toml', '.lock', '.csv', '.svg'}
FINDING_ID = re.compile(r'\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-[0-9]+\b')
NOT_A_FINDING = re.compile(r'(?:SHA|UTF|ISO|CVE|GHSA|RFC|PEP|TLS|SSL|AES|RSA|HTTP|ES|P|X|H|U)-')


def invariants(text):
    """`- invariant: KEY | family N | STATUS | sentence` lines; the last line for a key wins."""
    found = {}
    for raw in INVARIANT.findall(text):
        parts = [p.strip() for p in re.sub(r'[`*]', '', raw).split('|')]
        if len(parts) < 3:
            continue
        key, family = parts[0], FAMILY.fullmatch(parts[1])
        status = re.sub(r'\s+', '-', parts[2].upper())
        status = 'ROUND1-ESCAPE' if status == 'ESCAPE' else status
        families = sorted({int(f) for f in re.findall(r'[0-9]+', family.group(1))}) if family else []
        if KEY.fullmatch(key) and families and all(1 <= f <= 10 for f in families) and status in STATUSES:
            found[key] = {'families': families, 'status': status, 'sentence': ' | '.join(parts[3:])}
    return found


def recorded(root, starts, ends):
    """(attempt, final prose) for every recorded review, in ledger order."""
    rows = []
    for n in sorted(starts):
        end = ends.get(n, {})
        path = root / f'round-{n:04}' / 'ARTIFACT.md'
        if end.get('executed') and end.get('recorded', end.get('accepted')) and path.is_file():
            rows.append((n, path.read_text(encoding='utf-8', errors='replace')))
    return rows


def recurring(reviews):
    """Keys still OPEN, ROUND1-ESCAPE or REGRESSION in each of the two latest recorded reviews."""
    if len(reviews) < 2:
        return []
    before, latest = invariants(reviews[-2][1]), invariants(reviews[-1][1])
    return sorted(key for key, item in latest.items()
                  if item['status'] in RECURRING and before.get(key, {}).get('status') in RECURRING)


def tracked(reviews):
    """Latest report for every key, with the attempts that reported it open."""
    rows = {}
    for n, text in reviews:
        for key, item in invariants(text).items():
            row = rows.setdefault(key, {'open_rounds': []})
            row.update(item, round=n)
            if item['status'] in RECURRING:
                row['open_rounds'].append(n)
    return rows


def carried(rows):
    lines = [f"- {key} | family {','.join(map(str, row['families']))} | {row['status']} in attempt "
             f"{row['round']}; open in attempts {', '.join(map(str, row['open_rounds'])) or 'none'} | "
             f"{row['sentence']}" for key, row in rows.items() if row['status'] != 'CLOSED']
    return '\n' + '\n'.join(lines) if lines else 'none'


def write_atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', delete=False) as f:
        f.write(data)
        temporary = f.name
    os.replace(temporary, path)
    return path


def redesign_request(root, keys, rows):
    """Render the SKILL.md template into REDESIGN-REQUIRED.md for the implementer to answer."""
    values = {'INVARIANT_KEYS': ', '.join(keys),
              'RECURRENCE': '; '.join(f"{key} open in attempts {', '.join(map(str, rows[key]['open_rounds']))}"
                                      for key in keys)}
    rendered = subprocess.run([sys.executable, str(HERE / 'render-prompt.py'), str(SKILL), 'redesign',
                               '--values-stdin'], input=json.dumps(values).encode(),
                              capture_output=True, env=child_environment())
    require(rendered.returncode == 0, 'redesign-template', rendered.stderr.decode().strip())
    return write_atomic(root / 'REDESIGN-REQUIRED.md', rendered.stdout)


def repair_shape(patch):
    """(added code lines, of which conditionals or early exits), outside tests and prose files."""
    code = branches = 0
    path = None
    for line in patch.decode('utf-8', 'replace').splitlines():
        if line.startswith('+++ '):
            path = line[6:] if line.startswith('+++ b/') else None
            if path and (TEST_PATH.search(path) or Path(path).suffix.lower() in PROSE_SUFFIXES):
                path = None
        elif line.startswith('+') and path:
            body = line[1:].strip()
            if body and not body.startswith(COMMENT):
                code += 1
                branches += bool(BRANCH.search(body))
    return code, branches


def shape_warning(rows, latest_round, patch):
    """Advisory: a family-5 invariant answered mostly with new branches on the output's shape."""
    keys = [key for key, row in rows.items()
            if row['round'] == latest_round and row['status'] in RECURRING and 5 in row['families']]
    code, branches = repair_shape(patch)
    if not keys or not branches or branches * 2 < code:
        return None
    return (f'repair-shape heuristic: {branches} of {code} added non-test code lines since attempt '
            f'{latest_round} are conditionals or early exits, while shape-mistaken-for-provenance '
            f'invariant(s) {", ".join(keys)} stayed open. That family usually closes where the output '
            'is produced, by recording its provenance, not by another branch on its shape. Advisory only.')


def unreceipted(response, texts):
    """Finding IDs the implementer cites that no review recorded for this PR contains."""
    known = set()
    for text in texts:
        known.update(FINDING_ID.findall(text))
    cited = dict.fromkeys(i for i in FINDING_ID.findall(response) if not NOT_A_FINDING.match(i))
    return [i for i in cited if i not in known]


def executed_texts(root, ends):
    texts = []
    for n, end in sorted(ends.items()):
        path = root / f'round-{n:04}' / 'ARTIFACT.md'
        if end.get('executed') and 'ARTIFACT.md' in end.get('outputs', {}) and path.is_file():
            texts.append(path.read_text(encoding='utf-8', errors='replace'))
    return texts


def summary(root, starts, ends, originals):
    rows = tracked(recorded(root, starts, ends))
    if rows:
        print('contract invariants (reviewer lines; a review without them reported none):')
        for key, row in rows.items():
            print(f"  {key} family {','.join(map(str, row['families']))}: {row['status']} in attempt "
                  f"{row['round']}; open in attempts {', '.join(map(str, row['open_rounds'])) or 'none'}")
    keys = recurring(recorded(root, starts, ends))
    if keys:
        print('REDESIGN_REQUIRED before another review: ' + ', '.join(keys))
    witnesses, _ = evidence.view(root, starts, ends)
    if witnesses:
        print('witness ledger:')
        for line in evidence.ledger_rows(witnesses):
            print('  ' + line[2:])


def cell(text):
    return str(text).replace('|', '\\|').replace('\n', ' ')


def write_handoff(root, head, starts, ends, originals, reason):
    """A decision document. The findings stay in the reviews; nothing here closes or approves."""
    reviews = recorded(root, starts, ends)
    rows = tracked(reviews)
    pr = next((s.get('pr') for s in starts.values() if s.get('pr')), root.name)
    lines = [f'# Review handoff: {pr}', '', f'Requested head: {head}', f'Reason: {reason}.',
             ledger.cumulative(root, starts) + '.', '',
             'No automatic review will run for this PR without a new recorded grant. '
             'Nothing here authorizes a merge.', '', '## Findings', '',
             "The remaining findings are in the reviewers' own words; the host does not extract them."]
    if originals:
        n, directory, start, _ = originals[-1]
        lines.append(f"- Original review: attempt {n}, head {start['head_sha']}: {directory / 'ARTIFACT.md'}")
    if reviews:
        n = reviews[-1][0]
        lines.append(f"- Latest recorded review: attempt {n}, head {starts[n]['head_sha']}: "
                     f"{root / f'round-{n:04}' / 'ARTIFACT.md'}")
    else:
        lines.append('- No recorded review exists for this PR.')
    unusable = [n for n in starts if not ends.get(n, {}).get('recorded', ends.get(n, {}).get('accepted'))]
    if unusable:
        lines.append('- Failed or interrupted attempts: ' + ', '.join(map(str, unusable)))
    lines += ['', '## Contract invariants', '']
    if rows:
        lines += ['| key | family | latest status | attempt | open in attempts | invariant |',
                  '|---|---|---|---|---|---|']
        lines += [f"| {cell(key)} | {','.join(map(str, row['families']))} | {row['status']} | {row['round']} | "
                  f"{', '.join(map(str, row['open_rounds'])) or 'none'} | {cell(row['sentence'])} |"
                  for key, row in rows.items()]
    else:
        lines.append('No review reported a contract invariant line. That is not evidence that none is open.')
    lines += ['', '## Witnesses', '']
    witnesses = evidence.view(root, starts, ends)[0]
    lines += evidence.ledger_rows(witnesses) or ['No preserved witness.']
    redesigned = [n for n in starts if 'IMPLEMENTER_REDESIGN.md' in starts[n].get('inputs', {})
                  and starts[n].get('redesign_supplied')]
    keys = recurring(reviews)
    lines += ['', '## Redesign', '']
    lines.append(f'Latest supplied redesign: attempt {redesigned[-1]}.' if redesigned
                 else 'No redesign was supplied.')
    if keys:
        lines.append(f"Still open in two consecutive reviews: {', '.join(keys)}. "
                     f"Template: {root / 'REDESIGN-REQUIRED.md'}")
    lines += ['', '## Decision requested', '',
              'Record who decides and choose one:', '',
              '- [ ] Redesign: replace the path-by-path repairs with one enforcement point, then grant a '
              'supplementary review of that design.',
              '- [ ] Shrink the contract: stop promising the behavior on the paths still failing, and route '
              'them as separate issues.',
              '- [ ] Accept the risk and merge: name each open finding accepted and who owns it.',
              '- [ ] Hold or close the change.', '']
    return write_atomic(root / 'HANDOFF.md', '\n'.join(lines).encode())
