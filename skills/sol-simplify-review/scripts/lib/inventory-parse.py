#!/usr/bin/env python3
"""Read the round-1 inventory as data.

SKILL.md fixes the artifact's shape exactly -- headings, item fields, a two-axis
verdict. That makes the artifact checkable without a second schema beside it, which
matters twice over: a JSON schema next to the Markdown would be class G7 (a second
authority restating the first), and a schema-forced reviewer reliably returns a
complete envelope with nothing in it. The prompt stays question-shaped; the check
reads what came back.

Modes:
  --accounting   FILE            -> JSON {filesRead, filesReadDiffOnly, notRead}
  --check-shape  FILE ROUND      -> exit 1 if required sections are missing
  --check-verdict FILE           -> exit 1 if the verdict contradicts the items
  --check-items  FILE            -> exit 1 on N/A without a reason, FAIL without a sweep
"""
import json, re, sys

ROUND1_SECTIONS = ["# Round 1 review inventory", "## Binding", "## File accounting",
                   "## Inventory", "## Verdict"]
ROUND2_SECTIONS = ["# Round 2 closure review", "## Binding", "## Closure", "## Verdict"]

# "- <path> — READ | READ_DIFF_ONLY | NOT_READ — <role>". Em dash is what SKILL.md
# prints; a reviewer typing a hyphen instead is following the shape, not breaking it,
# so both separate.
ACCT = re.compile(r"^\s*[-*]\s+(?:`)?([^`\n—|]+?)(?:`)?[ \t]*(?:—|--|–)[ \t]*"
                  r"(READ_DIFF_ONLY|NOT_READ|READ)\b", re.M)


def section(text, heading, stop_prefix="## "):
    i = text.find(heading)
    if i < 0:
        return ""
    j = text.find("\n" + stop_prefix, i + len(heading))
    return text[i:j if j > 0 else len(text)]


def accounting(text):
    body = section(text, "## File accounting")
    out = {"filesRead": [], "filesReadDiffOnly": [], "notRead": []}
    key = {"READ": "filesRead", "READ_DIFF_ONLY": "filesReadDiffOnly", "NOT_READ": "notRead"}
    for path, status in ACCT.findall(body):
        path = path.strip()
        # The template line itself is not a claim about a file.
        if path.startswith("<"):
            continue
        out[key[status]].append(path)
    return out


def fields(text):
    out, key = {}, None
    for line in text.splitlines():
        m = re.match(r'^[-*] ([A-Za-z_][A-Za-z0-9_ ]*):[ \t]*(.*)$', line)
        if m:
            key = m[1].lower()
            if key in out:
                raise ValueError('GUARD FAIL [duplicate-field] ' + key)
            out[key] = m[2].strip()
        elif key and line.startswith('  ') and line.strip():
            out[key] += ' ' + line.strip()
        elif line.startswith('#'):
            key = None
    return out


def items(text):
    """Every '### <ID> — ...' block with its '- field: value' pairs."""
    body = section(text, "## Inventory", stop_prefix="## ")
    out = []
    for m in re.finditer(r"^###\s+([A-Za-z0-9-]+)\s*(?:—|--|–)?\s*(.*)$", body, re.M):
        start = m.end()
        nxt = re.search(r"^###\s+", body[start:], re.M)
        block = body[start:start + nxt.start()] if nxt else body[start:]
        out.append({"id": m.group(1), "title": m.group(2), "fields": fields(block)})
    return out


def empty(v):
    return not v or v.lower() in {"none", "n/a", "na", "-", "not applicable", "<none>"}


def fail(msg):
    print("GUARD FAIL " + msg, file=sys.stderr)
    return 1


def check_shape(text, rnd):
    want = ROUND1_SECTIONS if str(rnd) == "1" else ROUND2_SECTIONS
    missing = [h for h in want if h not in text]
    if missing:
        return fail("[shape] round-%s artifact is missing: %s" % (rnd, ", ".join(missing)))
    if str(rnd) == "1":
        if not accounting(text)["filesRead"] and not accounting(text)["filesReadDiffOnly"]:
            return fail("[shape] File accounting lists no READ file -- the section is present "
                        "and empty, which is the shape a skipped review produces")
        if not items(text):
            return fail("[shape] Inventory contains no '### <ID>' item")
    return 0


def check_verdict(text):
    v = section(text, "## Verdict", stop_prefix="\n#")
    def field(name):
        m = re.search(r"^\s*[-*]?\s*%s:\s*([A-Z_ ]+)" % name, v, re.M)
        return m.group(1).strip() if m else ""
    enumeration, verification = field("enumeration"), field("verification")
    verdict = field("verdict") or (re.search(r"^\s*(PASS|BLOCK|INCOMPLETE)\b", v.split("\n", 1)[-1],
                                             re.M).group(1) if re.search(
        r"^\s*(PASS|BLOCK|INCOMPLETE)\b", v.split("\n", 1)[-1], re.M) else "")
    rc = 0
    if not enumeration or not verification:
        rc |= fail("[verdict] the two axes are not both reported "
                   "(enumeration=%r verification=%r)" % (enumeration, verification))
    blockers = [i for i in items(text)
                if i["fields"].get("status", "").upper().startswith("FAIL")
                and i["fields"].get("impact", "").upper().startswith("BLOCKER")]
    if blockers and not verdict.startswith("BLOCK"):
        rc |= fail("[verdict] %d BLOCKER FAIL item(s) reproduced (%s) but verdict is %r. "
                   "A reproduced blocker is a fact; an unfinished sweep does not unmake it."
                   % (len(blockers), ", ".join(i["id"] for i in blockers), verdict))
    if verdict.startswith("PASS") and enumeration.startswith("INCOMPLETE"):
        rc |= fail("[verdict] PASS requires COMPLETE enumeration; enumeration is INCOMPLETE")
    unver = [i["id"] for i in items(text) if i["fields"].get("status", "").upper() == "UNVERIFIED"]
    if unver and verification.startswith("COMPLETE"):
        rc |= fail("[verdict] verification is COMPLETE but %d item(s) are UNVERIFIED: %s"
                   % (len(unver), ", ".join(unver)))
    return rc


def check_items(text):
    rc = 0
    seen = set()
    for it in items(text):
        if it["id"] in seen:
            rc |= fail("[item] duplicate ID " + it["id"])
        seen.add(it["id"])
        f, st = it["fields"], it["fields"].get("status", "").upper()
        for req in ("status", "impact", "must_hold", "applicable_sites"):
            if req not in f:
                rc |= fail("[item] %s has no `%s` field" % (it["id"], req))
        if st == "N/A" and empty(f.get("evidence", "")) and empty(f.get("source", "")):
            rc |= fail("[item] %s is N/A with no stated reason -- SKILL.md allows N/A only "
                       "with a concrete reason" % it["id"])
        if st.startswith("FAIL"):
            if empty(f.get("failing_sites", "")):
                rc |= fail("[item] %s is FAIL with no failing_sites" % it["id"])
            if empty(f.get("class_sweep", "")):
                rc |= fail("[item] %s is FAIL with an empty class_sweep -- FAIL is not valid "
                           "when only the first failing site was examined; use UNVERIFIED"
                           % it["id"])
            if empty(f.get("reproduction", "")):
                rc |= fail("[item] %s is FAIL with no reproduction" % it["id"])
    return rc


def main(argv):
    mode, path = argv[1], argv[2]
    text = open(path, encoding="utf-8", errors="replace").read()
    if mode == "--accounting":
        json.dump(accounting(text), sys.stdout, indent=1)
        return 0
    if mode == "--check-shape":
        return check_shape(text, argv[3] if len(argv) > 3 else "1")
    if mode == "--check-verdict":
        return check_verdict(text)
    if mode == "--check-items":
        return check_items(text)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (ValueError, OSError) as e:
        sys.exit(str(e))
