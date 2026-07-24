#!/usr/bin/env sh
# Speak one line through Qantara. Usage: ./speak.sh "hello there"
curl -s -X POST http://127.0.0.1:8765/api/v1/speak \
  -H 'Content-Type: application/json' \
  -d "{\"text\": \"${1:-hello from qantara}\"}" > /tmp/qantara-say.wav && aplay -q /tmp/qantara-say.wav
