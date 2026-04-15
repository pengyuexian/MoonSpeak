#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "$#" -ne 1 ]; then
  echo "Usage: scripts/run_assessment.sh <audio_file>" >&2
  exit 1
fi

cd "$ROOT_DIR"

RESULT_JSON="$(conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m moonspeak.run_assessment "$1")"

python3 -c 'import json,sys; data=json.loads(sys.argv[1]); print(data["report_url"] if data.get("success") else data["error"]); sys.exit(0 if data.get("success") else 1)' "$RESULT_JSON"
