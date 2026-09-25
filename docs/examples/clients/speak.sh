#!/usr/bin/env sh
# Speak one line through Qantara. Usage: ./speak.sh "hello there"
# Optional: QANTARA_URL (default http://127.0.0.1:8765), QANTARA_AUTH_TOKEN.
# Requires python3 (for safe JSON encoding) and aplay (ALSA) for playback.
set -eu
text="${1:-hello from qantara}"
url="${QANTARA_URL:-http://127.0.0.1:8765}"
out="$(mktemp "${TMPDIR:-/tmp}/qantara-say.XXXXXX")"
trap 'rm -f "$out"' EXIT

# json.dumps escapes quotes, backslashes and newlines in the text.
body="$(python3 -c 'import json, sys; print(json.dumps({"text": sys.argv[1]}))' "$text")"

if [ -n "${QANTARA_AUTH_TOKEN:-}" ]; then
  curl -sS --fail -X POST "$url/api/v1/speak" \
    -H 'Content-Type: application/json' \
    -H "Authorization: Bearer $QANTARA_AUTH_TOKEN" \
    --data-binary "$body" -o "$out"
else
  curl -sS --fail -X POST "$url/api/v1/speak" \
    -H 'Content-Type: application/json' \
    --data-binary "$body" -o "$out"
fi
aplay -q "$out"
