#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${APP_DIR:-/app}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$APP_DIR"

ls -la "${APP_DIR}/data/corpus"
wc -l "${APP_DIR}/data/corpus/"*.py
head -n 3 "${APP_DIR}/data/rule_registry.json"
head -n 3 "${APP_DIR}/data/stale_rule_pack.json"
head -n 5 "${APP_DIR}/data/reference_finding_grid.json"
jq '.active_rules | length' "${APP_DIR}/data/rule_registry.json"
jq '.active_rules' "${APP_DIR}/data/stale_rule_pack.json"
jq '.expected_findings | length' "${APP_DIR}/data/reference_finding_grid.json"
jq '.rule_dependency_graph.expected_closure | length' "${APP_DIR}/data/reference_finding_grid.json"
test -f "${APP_DIR}/work/lint_reconcile_policy.json"
grep -c prefer_regex "${APP_DIR}/work/lint_reconcile_policy.json" || true
grep -l rule_pattern_merge_lane "${APP_DIR}/"*.py 2>/dev/null || true
grep -l rule_pattern_authority "${APP_DIR}/"*.py 2>/dev/null || true
wc -c "${APP_DIR}/ast_visit_dispatch_bridge.py"
python3 -c "import ast; print('ast ok')"
"$PYTHON_BIN" -c "import json; r=json.load(open('${APP_DIR}/data/rule_registry.json')); print(len(r['rule_dependency_graph']['expected_closure']))"

rm -f "${APP_DIR}/output"/* 2>/dev/null || true
mkdir -p "${APP_DIR}/output"

"$PYTHON_BIN" - <<PY
import json
from pathlib import Path

app = Path("${APP_DIR}")
registry = json.loads((app / "data/rule_registry.json").read_text())
ref = json.loads((app / "data/reference_finding_grid.json").read_text())
graph = registry["rule_dependency_graph"]
expected_rules = set(graph["expected_closure"])
roots = registry["active_rules"]
edges = graph.get("edges", [])
adj = {}
for e in edges:
    adj.setdefault(e["from"], []).append(e["to"])
seen = set()
stack = list(roots)
while stack:
    n = stack.pop()
    if n in seen:
        continue
    seen.add(n)
    stack.extend(adj.get(n, []))
missing = sorted(expected_rules - seen)
plan = {
    "case_id": registry.get("case_id"),
    "expected_finding_count": len(ref["expected_findings"]),
    "expected_rule_closure_size": len(expected_rules),
    "missing_rules_after_one_hop": missing,
    "corpus_file_count": len(ref["corpus_files"]),
    "must_enable_authority_lane": True,
}
work = app / "work"
work.mkdir(parents=True, exist_ok=True)
(work / "repair_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
print(json.dumps(plan))
PY

cp "${SCRIPT_DIR}/patches/"*.py "${APP_DIR}/"
"$PYTHON_BIN" lint_policy_runner.py

test -f "${APP_DIR}/output/lint_scan_report.json"
"$PYTHON_BIN" -c "import json,sys; d=json.load(open('${APP_DIR}/output/lint_scan_report.json')); sys.exit(0 if d.get('scan_complete') else 1)"
"$PYTHON_BIN" -c "import json,sys; d=json.load(open('${APP_DIR}/output/scan_summary.json')); sys.exit(0 if d.get('scan_reconciled') else 1)"
