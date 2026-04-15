#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"
exec conda run --no-capture-output -n moonspeak env PYTHONPATH=.:src python -m server.http_server
