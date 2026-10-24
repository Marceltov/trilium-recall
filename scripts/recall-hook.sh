#!/bin/bash
# UserPromptSubmit hook: asks the recall engine whether the wiki knows something about this
# prompt and, if so, hands Claude the hits as additional context. It must never get in the way:
# no config, a slow or broken engine, or any other failure → no output, exit 0.
set -u

data_dir="${CLAUDE_PLUGIN_DATA:-${CLAUDE_CONFIG_DIR:-$HOME/.claude}/plugin-data/trilium-llm-wiki}"
config="$data_dir/recall.json"
# Always drain stdin: exiting with a large prompt unread leaves the writer a broken pipe.
[ -f "$config" ] || { cat >/dev/null; exit 0; }

# One python call reads the hook input (stdin: a pasted log can exceed the argv limit) and the
# config and builds the request body. The engine embeds only the start of a prompt, so 20000
# characters are plenty. The token travels via a curl config on stdin, never on the command line.
request=$(python3 -I -c '
import json, sys
raw = sys.stdin.read()
try:
    hook = json.loads(raw)
    cfg = json.load(open(sys.argv[1]))
    url, token = cfg["url"].rstrip("/"), cfg["token"]
    body = {"prompt": (hook.get("prompt") or "")[:20000], "session_id": hook.get("session_id"), "cwd": hook.get("cwd")}
except Exception:
    sys.exit(1)
print(url + "/recall")
print(token)
print(json.dumps(body))
' "$config" 2>/dev/null) || exit 0

url=$(sed -n 1p <<<"$request")
token=$(sed -n 2p <<<"$request")
body=$(sed -n 3p <<<"$request")

response=$(printf 'header = "Authorization: Bearer %s"\n' "$token" |
  curl -sS --fail --max-time 1.5 -K - -H 'Content-Type: application/json' --data "$body" "$url" 2>/dev/null) || exit 0

python3 -I -c '
import json, sys
try:
    context = json.loads(sys.argv[1]).get("context") or ""
except Exception:
    sys.exit(0)
if context:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}}))
' "$response" 2>/dev/null
exit 0
