"""Deterministic checks on the Markdown handoff; product truth stays with the reviewer."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('inventory_parse', HERE / 'inventory-parse.py')
inv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inv)


class Rejected(Exception):
    pass


def require(condition, tag, reason):
    if not condition:
        raise Rejected(f'GUARD FAIL [{tag}] {reason}')


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fields(text):
    try:
        return inv.fields(text)
    except ValueError as e:
        raise Rejected(str(e)) from e


def section(text, name):
    return inv.section(text, '## ' + name)


def meaningful(value):
    return not inv.empty(value) and not re.fullmatch(r'<[^>]*>', value.strip())


def blocks(text, heading, level='###'):
    out = {}
    body = section(text, heading) if heading else text
    pattern = rf'^{level} ([OGP]-\d+)\b([^\n]*)\n(.*?)(?=^#{{1,{len(level)}}} |\Z)'
    for m in re.finditer(pattern, body, re.M | re.S):
        require(m[1] not in out, 'duplicate-item', m[1])
        out[m[1]] = (m[2].strip(' —–-'), fields(m[3]))
    return out


def axes(text):
    return fields(section(text, 'Verdict'))


def verdict(text):
    v = section(text, 'Verdict')
    named = fields(v).get('verdict')
    if named:
        return named
    m = re.search(r'^(PASS WITH NITS|PASS|BLOCK|INCOMPLETE|RESTART_ROUND_1|PROTOCOL_ERROR)[ \t]*$', v, re.M)
    return m[1] if m else ''


def changed(repo, base, head):
    raw = git(repo, 'diff', '--no-renames', '--name-only', '-z', base, head)
    return [p.decode('utf-8') for p in raw.split(b'\0') if p]


def hunks(repo, base, head):
    """Zero-context git hunks, plus one unit for a file with only binary/mode/empty changes.

    Disable rename detection: both rename endpoints are accounted, including rename+edit.
    File metadata is included in the first hunk's identity, never silently dropped.
    """
    result = []
    for path in changed(repo, base, head):
        patch = git(repo, 'diff', '--no-ext-diff', '--no-textconv', '--no-renames',
                    '--binary', '--unified=0', base, head, '--', path)
        starts = [m.start() for m in re.finditer(rb'^@@ ', patch, re.M)]
        parts = []
        if starts:
            for i, start in enumerate(starts):
                end = starts[i + 1] if i + 1 < len(starts) else len(patch)
                unit = patch[start:end]
                label = unit.split(b'\n', 1)[0].decode('utf-8', 'replace')
                parts.append((label, (patch[:start] if i == 0 else b'') + unit))
        else:
            parts.append(('whole-file (binary, mode, or empty-file change)', patch))
        for label, unit in parts:
            identity = b'\0'.join([base.encode(), head.encode(), path.encode(), unit])
            result.append({'id': 'H-' + digest(identity)[:20], 'path': path, 'hunk': label})
    require(len({h['id'] for h in result}) == len(result), 'hunk-identity', 'duplicate hunk identity')
    return result


def hunk_markdown(rows):
    return '\n'.join(f"- {r['id']} {json.dumps(r['path'], ensure_ascii=False)} {r['hunk']} — <item ID or UNRELATED: explanation>" for r in rows) + '\n'


def sites(value):
    # Inventory sites are file:symbol or file:line. Backticks also permit spaces in paths.
    tokens = re.findall(r'`([^`]+:[^`]+)`|([^\s,;`]+:[^\s,;`]+)', value)
    return {(a or b).rstrip('.,;') for a, b in tokens}


def check_inventory(text, repo, base, head, expected_ids=()):
    require(inv.check_shape(text, 1) == 0 and inv.check_verdict(text) == 0
            and inv.check_items(text) == 0, 'inventory', 'invalid round-1 inventory')
    binding = fields(section(text, 'Binding'))
    for key, expected in [('base_sha', base), ('head_sha', head)]:
        require(binding.get(key) == expected, 'binding', f'{key} does not match host target')
    require(binding.get('basis') in {'SPECIFIED', 'DIFF_ONLY'}, 'binding', 'invalid basis')
    for key in ('repository', 'scope', 'full_suite', 'required_platforms', 'unavailable_evidence'):
        require(bool(binding.get(key)), 'binding', f'missing {key}')
    require(binding['scope'] in {'COMPLETE', 'INCOMPLETE'}, 'binding', 'invalid scope')
    items = blocks(text, 'Inventory')
    if verdict(text) == 'PASS':
        require(not any(f.get('status') == 'FAIL' for _, f in items.values()), 'verdict', 'PASS carries a FAIL item')
        unverified = {i for i, (_, f) in items.items() if f.get('status') == 'UNVERIFIED'}
        require(unverified <= set(re.findall(r'\b[OGP]-\d+\b', section(text, 'Verdict'))),
                'verdict', 'PASS must name every carried UNVERIFIED item')
    defaults = {f'G-{n:02}' for n in range(1, 11)}
    missing = sorted((defaults | set(expected_ids)) - items.keys())
    require(not missing, 'enumeration', 'missing required items: ' + ', '.join(missing))
    a = axes(text)
    require(a.get('enumeration') in {'COMPLETE', 'INCOMPLETE'} and
            a.get('verification') in {'COMPLETE', 'PARTIAL'}, 'enumeration', 'invalid coverage axes')
    require(verdict(text) in {'PASS', 'BLOCK', 'INCOMPLETE'}, 'verdict', 'unknown verdict')
    acct = inv.accounting(text)
    entries = acct['filesRead'] + acct['filesReadDiffOnly'] + acct['notRead']
    require(len(entries) == len(set(entries)), 'coverage', 'duplicate or contradictory file accounting')
    target = set(changed(repo, base, head))
    require(target <= set(entries), 'coverage', 'unaccounted files: ' + ', '.join(sorted(target - set(entries))))
    if acct['notRead']:
        require(a['enumeration'] == 'INCOMPLETE', 'enumeration', 'NOT_READ cannot claim COMPLETE')
    for path in acct['filesRead'] + acct['filesReadDiffOnly']:
        exists = any(subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', f'{sha}:{path}'],
                                   capture_output=True).returncode == 0 for sha in (head, base))
        require(exists, 'coverage', f'{path} exists at neither sealed endpoint')
    for ident, (_, f) in items.items():
        require(f.get('kind') == {'G': 'portable-class', 'O': 'obligation', 'P': 'project-class'}[ident[0]],
                'item', f'{ident}: ID and kind disagree')
        for key in ('source', 'must_hold', 'applies_to', 'evidence'):
            require(meaningful(f.get(key, '')), 'item', f'{ident}: empty {key}')
        st = f.get('status')
        require(st in {'PASS', 'FAIL', 'N/A', 'UNVERIFIED', 'NOTED'}, 'item', f'{ident}: invalid status')
        require(f.get('impact') in {'BLOCKER', 'NIT'}, 'item', f'{ident}: invalid impact')
        if st in {'PASS', 'FAIL', 'NOTED'}:
            for key in ('applicable_sites', 'class_sweep'):
                require(meaningful(f.get(key, '')), 'sibling-sweep', f'{ident}: empty {key}')
        if st == 'FAIL':
            require(bool(sites(f.get('failing_sites', ''))) and
                    sites(f['failing_sites']) <= sites(f.get('applicable_sites', '')),
                    'sibling-sweep', f'{ident}: failing sites must be in applicable_sites')
            require(meaningful(f.get('closure', '')), 'sibling-sweep', f'{ident}: empty closure')
        if st == 'NOTED':
            require(meaningful(f.get('dismissed_sites', '')), 'item', f'{ident}: NOTED needs dismissed_sites')
    return items


def check_response(text, inventory, repo, base, head, expected_digest):
    binding = fields(text.split('\n## ', 1)[0])
    for key, expected in [('inventory_sha256', expected_digest), ('round1_head_sha', base),
                          ('remediation_head_sha', head)]:
        require(binding.get(key) == expected, 'response-binding', f'{key} does not match sealed handoff')
    required = {i for i, (_, f) in blocks(inventory, 'Inventory').items() if f['status'] == 'FAIL'}
    responses = blocks(text, None, '##')
    require(set(responses) == required, 'response-items', 'FAIL dispositions missing or unknown: ' +
            ', '.join(sorted(set(responses) ^ required)))
    for ident, (_, f) in responses.items():
        require(f.get('disposition') in {'FIXED', 'DISPUTED'}, 'response-items', f'{ident}: invalid disposition')
        for key in ('changed_sites', 'applicable_siblings_checked', 'implementation',
                    'tests_added_or_changed', 'commands_and_results', 'remaining_limitations'):
            require(key in f and bool(f[key]), 'response-items', f'{ident}: missing {key}')
        require(meaningful(f.get('applicable_siblings_checked', '')), 'sibling-sweep', f'{ident}: no sibling check')
        applicable = sites(blocks(inventory, 'Inventory')[ident][1]['applicable_sites'])
        missing = applicable - sites(f['applicable_siblings_checked'])
        require(not missing, 'sibling-sweep', f'{ident}: unchecked siblings: ' + ', '.join(sorted(missing)))
    ids = blocks(inventory, 'Inventory').keys()
    rows = hunks(repo, base, head)
    actual = {}
    unrelated = []
    for line in section(text, 'Remediation hunk accounting').splitlines()[1:]:
        if not line.strip() or line.strip() in {'- none', 'none'}:
            continue
        m = re.fullmatch(r'- (H-[0-9a-f]{20})\b.*? — (.+)', line)
        require(m is not None, 'hunk-accounting', 'use generated H-ID and item IDs or UNRELATED: explanation')
        ident, dest = m.groups()
        require(ident not in actual, 'hunk-accounting', f'{ident}: duplicate mapping')
        if dest.startswith('UNRELATED:'):
            require(meaningful(dest.partition(':')[2].strip()), 'hunk-accounting', f'{ident}: empty unrelated explanation')
            unrelated.append(ident)
        else:
            mapped = {p.strip() for p in dest.split(',')}
            require(mapped <= ids and bool(mapped), 'hunk-accounting', f'{ident}: unknown inventory item {dest}')
        actual[ident] = dest
    expected = {r['id'] for r in rows}
    require(actual.keys() == expected, 'hunk-accounting', 'missing or stale hunks: ' +
            ', '.join(sorted(expected ^ actual.keys())))
    return unrelated


def check_closure(text, inventory, head, expected_digest):
    require(inv.check_shape(text, 2) == 0, 'closure', 'missing closure structure')
    original = blocks(inventory, 'Inventory')
    binding = fields(section(text, 'Binding'))
    r1head = fields(section(inventory, 'Binding')).get('head_sha')
    for key, expected in [('inventory_sha256', expected_digest), ('round1_head_sha', r1head),
                          ('remediation_head_sha', head), ('integrity', 'VERIFIED'),
                          ('ancestry', 'VERIFIED'), ('round1_scope', 'COMPLETE')]:
        require(binding.get(key) == expected, 'closure-binding', f'{key} does not match verified inputs')
    closure = blocks(text, 'Closure')
    required = {i for i, (_, f) in original.items() if f['status'] in {'FAIL', 'UNVERIFIED'}}
    require(required <= closure.keys() and closure.keys() <= original.keys(), 'closure-items',
            'missing or unknown closure IDs: ' + ', '.join(sorted((required - closure.keys()) | (closure.keys() - original.keys()))))
    for ident, (status, f) in closure.items():
        require(status in {'CLOSED', 'OPEN', 'UNVERIFIABLE'}, 'closure-items', f'{ident}: invalid closure status')
        for key in ('sites_verified', 'reproduction_result', 'tests', 'response_assessment', 'remaining_failure'):
            require(key in f and bool(f[key]), 'closure-items', f'{ident}: missing {key}')
        if status == 'CLOSED':
            missing = sites(original[ident][1].get('applicable_sites', '')) - sites(f['sites_verified'])
            require(not missing, 'closure-siblings', f'{ident}: unverified sites: ' + ', '.join(sorted(missing)))
            for key in ('sites_verified', 'reproduction_result', 'tests', 'response_assessment'):
                require(meaningful(f[key]), 'closure-evidence', f'{ident}: CLOSED without {key}')
    accounting = fields(section(text, 'Response and hunk accounting'))
    for key in ('response_items_missing', 'remediation_hunks_unexplained', 'touched_pass_or_na_items'):
        require(key in accounting, 'closure-accounting', f'missing {key}')
    for name in ('Remediation regressions', 'Protocol escapes'):
        require(bool(section(text, name)), 'closure', f'missing {name}')
    protocol_escapes(text, inventory)
    v = verdict(text)
    require(v in {'PASS', 'PASS WITH NITS', 'BLOCK', 'RESTART_ROUND_1', 'PROTOCOL_ERROR'}, 'closure-verdict', 'invalid verdict')
    if v.startswith('PASS'):
        for ident in required:
            st, f = original[ident][1]['status'], original[ident][1]
            if st == 'FAIL' and f['impact'] == 'NIT' and v == 'PASS WITH NITS':
                continue
            require(closure[ident][0] == 'CLOSED', 'closure-verdict', f'{ident} is not CLOSED')
        for name in ('Remediation regressions', 'Protocol escapes'):
            require(section(text, name).split('\n', 1)[-1].strip() in {'none', '- none'},
                    'closure-verdict', f'PASS carries {name.lower()}')
        for key in ('response_items_missing', 'remediation_hunks_unexplained'):
            require(accounting[key].lower() in {'none', '0'}, 'closure-verdict', f'PASS carries {key}')
    return closure


def escape_ids(text, inventory):
    """Every extra pass must name what escaped closure; this is not always ROUND1-ESCAPE."""
    rows = [line for line in text.splitlines() if line.startswith('- ')]
    require(bool(rows), 'round-budget', 'round 3+ requires item IDs and evidence in REVIEW_ESCAPES')
    known = blocks(inventory, 'Inventory')
    ids = set()
    for row in rows:
        m = re.fullmatch(r'- ([OGP]-\d+) — (OPEN|REMEDIATION-REGRESSION|ROUND1-ESCAPE|SCOPE-CHANGE|INTEGRITY) — (.+)', row)
        require(m is not None and m[1] in known and meaningful(m[3]), 'round-budget',
                'escape must name an original inventory ID, reason category, and evidence')
        ids.add(m[1])
    return sorted(ids)


def protocol_escapes(text, inventory):
    found = []
    known = blocks(inventory, 'Inventory')
    for line in section(text, 'Protocol escapes').splitlines()[1:]:
        if not line.strip() or line.strip() in {'none', '- none'}:
            continue
        category = re.search(r'\b(ROUND1-ESCAPE|SCOPE-CHANGE|INTEGRITY)\b', line)
        ids = set(re.findall(r'\b[OGP]-\d+\b', line))
        explanation = re.sub(r'ROUND1-ESCAPE|SCOPE-CHANGE|INTEGRITY|[OGP]-\d+', '', line).strip(' -—,:')
        require(category and ids and ids <= known.keys() and meaningful(explanation), 'escape-id',
                'protocol escape must name its original inventory class/obligation ID and evidence')
        found.extend((category[1], ident) for ident in sorted(ids))
    return found


def check_extra_round(text, inventory, prior_text, prior_phase, prior_accepted, changed_head, prior_escapes=""):
    ids = escape_ids(text, inventory)
    closure = blocks(prior_text, 'Closure') if prior_phase == 2 else {}
    recorded = protocol_escapes(prior_text, inventory) if prior_phase == 2 else []
    if prior_escapes:
        escape_ids(prior_escapes, inventory)
        recorded += [(row[2:].split(' — ', 2)[1], row[2:].split(' — ', 2)[0])
                     for row in prior_escapes.splitlines() if row.startswith('- ')]
    for line in text.splitlines():
        if not line.startswith('- '):
            continue
        ident, category, _ = line[2:].split(' — ', 2)
        if category == 'OPEN':
            require((ident in closure and closure[ident][0] in {'OPEN', 'UNVERIFIABLE'}) or (category, ident) in recorded,
                    'escape-evidence', f'{ident}: prior closure does not record OPEN/UNVERIFIABLE')
        elif category == 'ROUND1-ESCAPE':
            require((category, ident) in recorded, 'escape-evidence', f'{ident}: prior review has no ROUND1-ESCAPE')
        elif category == 'INTEGRITY':
            require(not prior_accepted or (category, ident) in recorded, 'escape-evidence', f'{ident}: prior guards did not reject the round')
        elif category == 'SCOPE-CHANGE':
            require(changed_head or (category, ident) in recorded, 'escape-evidence', f'{ident}: no changed head or recorded scope change')
        elif category == 'REMEDIATION-REGRESSION':
            regressions = section(prior_text, 'Remediation regressions').split('\n', 1)[-1].strip()
            require(changed_head or meaningful(regressions.strip('- ')), 'escape-evidence', f'{ident}: no new head or recorded remediation regression')
    return ids
