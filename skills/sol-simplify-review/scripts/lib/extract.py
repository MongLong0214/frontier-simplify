#!/usr/bin/env python3
"""Pull the reviewer's final artifact out of a codex/claude event stream.

Only the LAST agent message counts. An earlier message that happens to contain a
heading is a draft, and a draft that gets scored is a stored artifact approving
itself in miniature.

  extract.py EVENTS.jsonl "# Round 1 review inventory"   -> the artifact on stdout
"""
import json, sys

marker = sys.argv[2] if len(sys.argv) > 2 else "# Round 1 review inventory"
texts = []
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line:
        continue
    try:
        o = json.loads(line)
    except ValueError:
        continue
    item = o.get("item") or {}
    # codex: {"type":"item.completed","item":{"type":"agent_message","text":...}}
    if o.get("type") == "item.completed" and item.get("type") == "agent_message":
        texts.append(item.get("text", ""))
    # claude stream-json: {"type":"assistant","message":{"content":[{"type":"text",...}]}}
    if o.get("type") == "assistant":
        message = [c.get("text", "") for c in (o.get("message") or {}).get("content", [])
                   if c.get("type") == "text"]
        if message:
            texts.append("\n".join(message))
    if o.get("type") == "result" and isinstance(o.get("result"), str):
        texts.append(o["result"])

for t in texts[-1:]:
    i = t.find(marker)
    if i >= 0:
        # A fenced answer is still the answer; strip a trailing fence if the model wrapped it.
        body = t[i:]
        if body.rstrip().endswith("```"):
            body = body.rstrip()[: body.rstrip().rfind("```")]
        sys.stdout.write(body)
        sys.exit(0)
sys.exit(1)
