#!/usr/bin/env python3
"""Render a round prompt from SKILL.md.

SKILL.md is the authority for the prompt text. Copying it into a second file beside
the skill would be class G7 -- a formula restated outside its declared authority --
and the copy is what goes stale. So the harness reads the heading it needs and
substitutes the placeholders.

  render-prompt.py SKILL.md 1 KEY=VALUE ...
  render-prompt.py SKILL.md 1 --values-stdin
"""
import json
import re
import sys

def fail(message):
    sys.exit('render-prompt: ' + message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


if len(sys.argv) < 3:
    fail('expected SKILL.md, round and values')
skill, rnd = sys.argv[1:3]
args = sys.argv[3:]
if args == ['--values-stdin']:
    try:
        subs = json.loads(sys.stdin.buffer.read().decode('utf-8'), object_pairs_hook=unique_object)
    except (UnicodeError, ValueError):
        fail('values stdin must be a UTF-8 JSON object with unique string keys and values')
    if not isinstance(subs, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                              for k, v in subs.items()):
        fail('values stdin must be a UTF-8 JSON object with unique string keys and values')
else:
    if '--values-stdin' in args or any('=' not in a for a in args):
        fail('use either KEY=VALUE arguments or --values-stdin')
    subs = dict(a.split('=', 1) for a in args)
try:
    text = open(skill, encoding='utf-8').read()
except (OSError, UnicodeError):
    fail('cannot read prompt source')

m = re.search(r"^## Round %s prompt\s*$" % re.escape(rnd), text, re.M)
if not m:
    sys.exit("render-prompt: SKILL.md has no '## Round %s prompt' heading" % rnd)
fence = re.search(r"^```\w*\n(.*?)^```", text[m.end():], re.S | re.M)
if not fence:
    sys.exit("render-prompt: no fenced block under '## Round %s prompt'" % rnd)
body = fence.group(1)

token = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
left = sorted(set(token.findall(body)) - subs.keys())
if left:
    # An unsubstituted placeholder reaches the reviewer as the literal string
    # "{{BASE_SHA}}", and a reviewer that reviews a placeholder still answers.
    sys.exit("render-prompt: unsubstituted placeholders: " + ", ".join(left))
try:
    sys.stdout.buffer.write(token.sub(lambda match: subs[match.group(1)], body).encode('utf-8'))
except UnicodeError:
    fail('rendered prompt is not valid UTF-8')
