#!/bin/bash
# Self-check for recall-hook.sh against a stub engine. No framework:
# run `bash scripts/test-recall-hook.sh`.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
hook="$script_dir/recall-hook.sh"
tmp="$(mktemp -d)"
stub_pid=""
trap '[ -n "$stub_pid" ] && kill "$stub_pid" 2>/dev/null; rm -rf "$tmp"' EXIT

export CLAUDE_PLUGIN_DATA="$tmp/plugin-data"
fail=0
input='{"session_id":"sess-1","cwd":"/root/trilium","hook_event_name":"UserPromptSubmit","prompt":"why is CT 115 slow"}'

# Stub engine: behaviour picked by $tmp/mode; records each request body in $tmp/last-request.
cat > "$tmp/stub.py" <<'PY'
import http.server, json, sys, time
tmp = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        open(f"{tmp}/last-request", "w").write(json.dumps({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(body)}))
        mode = open(f"{tmp}/mode").read().strip()
        if mode == "slow":
            time.sleep(5)
        status, payload = {"context": (200, json.dumps({"context": "Wiki recall (x) — hit"})),
                           "empty": (200, json.dumps({"context": ""})),
                           "error": (500, "boom"), "garbage": (200, "not json"),
                           "slow": (200, json.dumps({"context": "late"}))}[mode]
        self.send_response(status); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(payload.encode())
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
open(f"{tmp}/port", "w").write(str(srv.server_address[1]))
srv.serve_forever()
PY
echo context > "$tmp/mode"
python3 -I "$tmp/stub.py" "$tmp" & stub_pid=$!
for _ in $(seq 1 50); do [ -s "$tmp/port" ] && break; sleep 0.1; done
port="$(cat "$tmp/port")"

run() {  # run <desc> <mode> <expect: context|none>
  local desc="$1" mode="$2" expect="$3" status=0 output start end
  echo "$mode" > "$tmp/mode"
  start=$(date +%s.%N)
  output=$(printf '%s' "$input" | "$hook") || status=$?
  end=$(date +%s.%N)
  if [ "$status" != 0 ]; then echo "FAIL ($desc): exit $status"; fail=1; return; fi
  if python3 -c "import sys; sys.exit(0 if float(sys.argv[2]) - float(sys.argv[1]) < 2.5 else 1)" "$start" "$end"; then :; else
    echo "FAIL ($desc): took too long"; fail=1; return; fi
  case "$expect" in
    context)
      python3 -c '
import json, sys
out = json.loads(sys.argv[1])["hookSpecificOutput"]
assert out["hookEventName"] == "UserPromptSubmit" and out["additionalContext"] == "Wiki recall (x) — hit", out
' "$output" || { echo "FAIL ($desc): unexpected output: $output"; fail=1; return; } ;;
    none)
      [ -z "$output" ] || { echo "FAIL ($desc): expected no output, got: $output"; fail=1; return; } ;;
  esac
  echo "ok: $desc"
}

run "no config → silent" context none
mkdir -p "$CLAUDE_PLUGIN_DATA"
printf '{"url": "http://127.0.0.1:%s", "token": "tok-123"}' "$port" > "$CLAUDE_PLUGIN_DATA/recall.json"
run "context is injected" context context
python3 -c '
import json, sys
r = json.load(open(sys.argv[1]))
assert r["path"] == "/recall" and r["auth"] == "Bearer tok-123", r
assert r["body"] == {"prompt": "why is CT 115 slow", "session_id": "sess-1", "cwd": "/root/trilium"}, r
' "$tmp/last-request" && echo "ok: request carries prompt, session_id, cwd and the token" || { echo "FAIL: request body"; fail=1; }
run "empty context → silent" empty none
run "HTTP 500 → silent" error none
run "non-JSON → silent" garbage none
run "slow engine → silent within the time limit" slow none
printf '{"url": "http://127.0.0.1:1", "token": "t"}' > "$CLAUDE_PLUGIN_DATA/recall.json"
run "engine down → silent" context none
echo 'not json' > "$CLAUDE_PLUGIN_DATA/recall.json"
run "broken config → silent" context none

exit "$fail"
