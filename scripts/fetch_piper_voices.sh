#!/usr/bin/env bash
# Fetch Piper voices for the 0.2.4 launch-5 language set.
# Run from repo root. Verify licenses before commercial redistribution.
set -euo pipefail

mkdir -p models/piper
cd models/piper

BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main"

# Spanish (Castilian)
curl -fLo es_ES-davefx-medium.onnx "${BASE}/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx"
curl -fLo es_ES-davefx-medium.onnx.json "${BASE}/es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json"

# French (France)
curl -fLo fr_FR-siwis-medium.onnx "${BASE}/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx"
curl -fLo fr_FR-siwis-medium.onnx.json "${BASE}/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json"

# Arabic (Jordan)
curl -fLo ar_JO-kareem-medium.onnx "${BASE}/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx"
curl -fLo ar_JO-kareem-medium.onnx.json "${BASE}/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json"

echo "Piper voices downloaded into $(pwd)"
echo "Japanese is not bundled — verify license + availability first."
