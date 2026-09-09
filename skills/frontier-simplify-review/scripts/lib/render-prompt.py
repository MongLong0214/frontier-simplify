#!/usr/bin/env python3
"""Render a round prompt from SKILL.md.

SKILL.md is the authority for the prompt text. Copying it into a second file beside
the skill would be class G7 -- a formula restated outside its declared authority --
and the copy is what goes stale. So the harness reads the heading it needs and
substitutes the placeholders.

  render-prompt.py SKILL.md 1 KEY=VALUE ...
"""
import re, sys

skill, rnd = sys.argv[1], sys.argv[2]
subs = dict(a.split("=", 1) for a in sys.argv[3:])
text = open(skill, encoding="utf-8").read()

m = re.search(r"^## Round %s prompt\s*$" % re.escape(rnd), text, re.M)
if not m:
    sys.exit("render-prompt: SKILL.md has no '## Round %s prompt' heading" % rnd)
fence = re.search(r"^```\w*\n(.*?)^```", text[m.end():], re.S | re.M)
if not fence:
    sys.exit("render-prompt: no fenced block under '## Round %s prompt'" % rnd)
body = fence.group(1)

for k, v in subs.items():
    body = body.replace("{{%s}}" % k, v)
left = sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", body)))
if left:
    # An unsubstituted placeholder reaches the reviewer as the literal string
    # "{{BASE_SHA}}", and a reviewer that reviews a placeholder still answers.
    sys.exit("render-prompt: unsubstituted placeholders: " + ", ".join(left))
sys.stdout.write(body)
