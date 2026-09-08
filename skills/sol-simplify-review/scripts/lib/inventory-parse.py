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
# Everything before the status separator is the file being accounted for; the reason after it is
# prose. A rename is one line naming two paths -- `old.json` -> `new.json` -- and both are changed
# files the seal will ask about, so both are captured. Measured: a complete inventory that accounted
# for all 34 changed files was rejected for 4 "missing" ones, because two rename lines named two
# paths each and the pattern could not read past the arrow. Reading a reason that mentions another
# file as an accounting claim would be the opposite error, so only the prefix is scanned.
ACCT = re.compile(r"^\s*[-*]\s+(.+?)[ \t]*(?:—|--|–)[ \t]*"
                  r"(READ_DIFF_ONLY|NOT_READ|READ)\b", re.M)
ACCT_BACKTICK = re.compile(r"`([^`\n]+)`")
ACCT_ARROW = re.compile(r"\s*(?:\u2192|->|=>)\s*")


def accounted_paths(prefix):
    """The paths one accounting line claims.

    Do not guess what a path looks like. Guessing cost this parser the fixture's
    `space name.txt` and its extensionless `empty` -- a pattern demanding a slash or an
    extension reads the first as `name.txt` and the second as nothing at all. The whole
    prefix is the path, and it is split only where the reviewer has explicitly marked two
    of them: backticks around each, or a rename arrow between them.
    """
    quoted = ACCT_BACKTICK.findall(prefix)
    if quoted:
        return quoted
    return [part for part in ACCT_ARROW.split(prefix) if part.strip()]


# Markdown emphasis is how a reviewer writes a verdict, not a way of hiding one. Measured: an
# inventory reporting `- verdict: **BLOCK**` with both axes in bold was rejected for reporting
# neither, because the pattern read only bare capitals. The value is read through the emphasis and
# stops at the first sentence, since the axes carry their reasoning on the same line.
EMPHASIS = re.compile(r"[*_`]+")


def enumerated(text):
    """The enumerated value a field line starts with, ignoring emphasis and trailing prose."""
    m = re.match(r"\s*([A-Za-z_ /]+)", EMPHASIS.sub("", text))
    return m.group(1).strip().rstrip(".").strip() if m else ""


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
    for prefix, status in ACCT.findall(body):
        for candidate in accounted_paths(prefix):
            path = candidate.strip()
            # The template line itself is not a claim about a file.
            if not path or path.startswith("<"):
                continue
            out[key[status]].append(path)
    return out


def fields(text):
    out, key = {}, None
    for line in text.splitlines():
        m = re.match(r'^[-*] ([A-Za-z_][A-Za-z0-9_ ]*):[ \t]*(.*)$', line)
        if m:
            key = m[1].lower()
            value = m[2].strip()
            # A field stated twice is rejected only when the two statements DISAGREE. That is the
            # whole point: an item whose `status:` says PASS in one line and FAIL in another has no
            # status, and picking the first or the last would be the parser deciding it. An
            # identical restatement decides nothing and is not ambiguous.
            #
            # Measured: a complete 73KB round-1 inventory carrying three reproduced BLOCKERs was
            # rejected because one item restated `status: PASS` after its `failing_sites: none`.
            # Rejecting a sound review for a harmless repetition is how a gate gets switched off,
            # and the guard was firing where its own rationale did not reach.
            if key in out and out[key] != value:
                raise ValueError('GUARD FAIL [conflicting-field] %s: %r vs %r' % (key, out[key], value))
            if key in out:
                continue
            out[key] = value
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
        m = re.search(r"^\s*[-*]?\s*%s:\s*(.+)$" % name, v, re.M)
        return enumerated(m.group(1)) if m else ""
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
