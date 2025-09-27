#!/usr/bin/env bash
# test.sh — start HTTP UI and WS depth server (no TLS). Supports WEBCAM_NAME/WEBCAM_INDEX.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
CLIENT_DIR="$DIR/client"
PY="$(command -v python3 || command -v python)"

HTTP_PORT="${HTTPS_PORT:-8443}"   # use as HTTP
PORT="${PORT:-8765}"              # WS port used by server.py
BIND_HOST="${BIND_HOST:-127.0.0.1}"

# default: real camera unless you set TEST_PATTERN=1
TEST_PATTERN="${TEST_PATTERN:-0}"

HTTP_PID=""
SERVER_PID=""
cleanup() {
  [[ -n "${SERVER_PID:-}" ]] && kill "$SERVER_PID" 2>/dev/null || true
  [[ -n "${HTTP_PID:-}"  ]] && kill "$HTTP_PID"  2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "🌐 HTTP static server on http://127.0.0.1:$HTTP_PORT (serving $CLIENT_DIR)…"
(
  cd "$CLIENT_DIR"
  HTTP_PORT="$HTTP_PORT" \
  exec "$PY" - <<'PY'
import http.server, socketserver, os
port = int(os.environ.get("HTTP_PORT","8443"))
handler = http.server.SimpleHTTPRequestHandler
with socketserver.TCPServer(('127.0.0.1', port), handler) as httpd:
    print(f"HTTP server ready at http://127.0.0.1:{port}", flush=True)
    httpd.serve_forever()
PY
) & HTTP_PID=$!

export TEST_PATTERN="$TEST_PATTERN"
export PORT="$PORT"
export BIND_HOST="$BIND_HOST"
# pass through camera selection envs if set
[[ -n "${WEBCAM_NAME:-}"  ]] && export WEBCAM_NAME
[[ -n "${WEBCAM_INDEX:-}" ]] && export WEBCAM_INDEX

echo "📡 WS depth server on ws://$BIND_HOST:$PORT (TEST_PATTERN=$TEST_PATTERN)…"
( cd "$DIR" && exec "$PY" server.py ) & SERVER_PID=$!

# --- wait for both servers to be ready ---
wait_tcp () { "$PY" - "$1" "$2" <<'PY'
import socket, sys, time
host, port = sys.argv[1], int(sys.argv[2])
deadline = time.time() + 15.0
last_err = None
while time.time() < deadline:
    try:
        s = socket.create_connection((host, port), timeout=1.0)
        s.close()
        sys.exit(0)
    except Exception as e:
        last_err = e
        time.sleep(0.2)
print(f"timeout waiting for {host}:{port} -> {last_err}")
sys.exit(1)
PY
}

wait_tcp 127.0.0.1 "$HTTP_PORT" || true
wait_tcp "$BIND_HOST" "$PORT" || true

OPEN_URL="http://127.0.0.1:$HTTP_PORT/?port=$PORT"
echo "🧭 $OPEN_URL"
if command -v open >/dev/null 2>&1; then open "$OPEN_URL" || true; fi

wait
