#!/usr/bin/env bash
# Fetch pinned, checksum-verified Piper voices: English, Spanish, French, Arabic.
# Run from repo root. Verify licenses before commercial redistribution.
#
# Files come from a fixed rhasspy/piper-voices revision and every file is
# checked against a pinned SHA-256 (the .onnx hashes are the Hugging Face
# LFS object ids). A mismatch deletes the file and fails the script.
set -euo pipefail

REVISION="c10ece1aade47bb51c153c893d14e5bf8e5b7117"
BASE="https://huggingface.co/rhasspy/piper-voices/resolve/${REVISION}"

# path-under-repo  sha256
VOICES=(
  # English (US) — registry voice id "lessac"
  "en/en_US/lessac/medium/en_US-lessac-medium.onnx 5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"
  "en/en_US/lessac/medium/en_US-lessac-medium.onnx.json efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0"
  # Spanish (Castilian)
  "es/es_ES/davefx/medium/es_ES-davefx-medium.onnx 6658b03b1a6c316ee4c265a9896abc1393353c2d9e1bca7d66c2c442e222a917"
  "es/es_ES/davefx/medium/es_ES-davefx-medium.onnx.json 0e0dda87c732f6f38771ff274a6380d9252f327dca77aa2963d5fbdf9ec54842"
  # French (France)
  "fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx 641d1ab097da2b81128c076810edb052b385decc8be3381814802a64a73baf99"
  "fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx.json 39479916c2db192b5ac9764daddd0c744d83e023ad890c6976c0633ae4df8959"
  # Arabic (Jordan)
  "ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx 9e95cab07b679da603bba17c4dec7ab3111320571964ee95c0379603c086491e"
  "ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx.json ea6d9b9d9076dbdb6bf5c98c6a141ef154959d2359709b37855727964e7d6c4d"
)

if command -v sha256sum >/dev/null 2>&1; then
  sha256_of() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
  sha256_of() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  echo "error: need sha256sum or shasum to verify downloads" >&2
  exit 1
fi

mkdir -p models/piper
cd models/piper

for item in "${VOICES[@]}"; do
  read -r path expected <<<"${item}"
  file="$(basename "${path}")"
  if [[ -f "${file}" && "$(sha256_of "${file}")" == "${expected}" ]]; then
    echo "ok (cached)  ${file}"
    continue
  fi
  curl -fL --retry 3 -o "${file}.part" "${BASE}/${path}"
  actual="$(sha256_of "${file}.part")"
  if [[ "${actual}" != "${expected}" ]]; then
    rm -f "${file}.part"
    echo "error: checksum mismatch for ${file}" >&2
    echo "  expected ${expected}" >&2
    echo "  actual   ${actual}" >&2
    exit 1
  fi
  mv "${file}.part" "${file}"
  echo "ok           ${file}"
done

echo "Piper voices downloaded and verified into $(pwd)"
echo "Japanese is not bundled — verify license + availability first."
