#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/app}"
PYTHON_BIN="${PYTHON_BIN:-python}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

cd "$APP_DIR"

ls -la "${APP_DIR}/data"
ls -la "${APP_DIR}/output" 2>/dev/null || true
wc -l "${APP_DIR}/data/sim_step_manifest.txt"
head -n 3 "${APP_DIR}/data/sim_step_manifest.txt"
tail -n 2 "${APP_DIR}/data/sim_step_manifest.txt"
grep -c gather_contacts "${APP_DIR}/data/sim_registry.json"
grep impulse "${APP_DIR}/data/sim_registry.json" | head -n 1
jq -r '.scenario_id' "${APP_DIR}/data/sim_scenario.json"
jq -r '.thread_buckets' "${APP_DIR}/data/sim_scenario.json"
jq -r '.frame_count' "${APP_DIR}/data/sim_scenario.json"
jq -r '.step_verbs.contact_gather' "${APP_DIR}/data/sim_registry.json"
jq -r '.step_verbs.contact_gather' "${APP_DIR}/data/sim_policy.json"
find "${APP_DIR}" -maxdepth 1 -name '*.py' | sort
find "${APP_DIR}/data" -type f | sort
test -f "${APP_DIR}/data/reference_frame_digests.json"
wc -c "${APP_DIR}/data/reference_frame_digests.json"
diff -q "${APP_DIR}/data/sim_registry.json" "${APP_DIR}/data/sim_policy.json" >/dev/null 2>&1 || true
"$PYTHON_BIN" -c "import json; d=json.load(open('${APP_DIR}/data/reference_frame_digests.json')); print(len(d['digests']))"
"$PYTHON_BIN" -c "from parallel_guard import thread_buckets_requested; import json; s=json.load(open('${APP_DIR}/data/sim_scenario.json')); print(thread_buckets_requested(s))"
test -d "${APP_DIR}/work" || mkdir -p "${APP_DIR}/work"
rm -rf "${APP_DIR}/output"/*
mkdir -p "${APP_DIR}/output"

cp "${SCRIPT_DIR}/patches/"*.py "${APP_DIR}/"
"$PYTHON_BIN" physics_sim_runner.py

test -f "${APP_DIR}/output/frame_digest_ledger.json"
test -f "${APP_DIR}/output/twin_run_verdict.json"
"$PYTHON_BIN" -c "import json,sys; d=json.load(open('${APP_DIR}/output/twin_run_verdict.json')); sys.exit(0 if d.get('twin_match') else 1)"
