#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/app}"
PYTHON_BIN="${PYTHON_BIN:-python}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

cd "$APP_DIR"
rm -rf "${APP_DIR}/output"/*
mkdir -p "${APP_DIR}/output"
cp "${SCRIPT_DIR}/patches/"*.py "${APP_DIR}/"
"$PYTHON_BIN" recovery_batch_runner.py
test -f "${APP_DIR}/output/patched_disk.img"
test -f "${APP_DIR}/output/geometry_attestation.json"
"$PYTHON_BIN" -c "import json,sys; d=json.load(open('${APP_DIR}/output/geometry_attestation.json')); sys.exit(0 if d.get('fsck_ready') and d.get('disk_probe_ok') else 1)"
test -f "${APP_DIR}/output/repair_summary.json"
"$PYTHON_BIN" -c "import json,sys; d=json.load(open('${APP_DIR}/output/repair_summary.json')); sys.exit(0 if d.get('reference_geometry_ok') and d.get('trace_chain_digest') and d.get('case_envelope_digest') else 1)"
