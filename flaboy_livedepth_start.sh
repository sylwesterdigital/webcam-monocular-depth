#!/usr/bin/env bash
set -euo pipefail

# LiveDepth reverse tunnel → flaboy.com
# - 9001 → your laptop's HTTPS viewer (8443, self-signed TLS)
# - 9002 → your laptop's WSS endpoint (8765, self-signed TLS)

REMOTE_HOST="yolo.cx"
REMOTE_USER="root"
REMOTE_PORT=18021

echo "🔌 Starting reverse tunnels for https://flaboy.com/livedepth …"

exec ssh -N \
  -p "${REMOTE_PORT}" \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -o TCPKeepAlive=yes \
  -o StrictHostKeyChecking=accept-new \
  -R 127.0.0.1:9001:127.0.0.1:8443 \
  -R 127.0.0.1:9002:127.0.0.1:8765 \
  "${REMOTE_USER}@${REMOTE_HOST}"
