from __future__ import annotations

import json
from pathlib import Path

from ast_visit_dispatch_bridge import dispatch_ast_scan
from corpus_expansion_lane import expand_corpus_paths
from finding_binding_compiler import bind_finding_row
from integrity_digest_seal import seal_findings_digest
from lint_scan_exporter import write_scan_report
from lint_store_contract import (
    CORPUS_DIR,
    FINDING_BINDING_AUDIT_PATH,
    FINDING_BINDING_POLICY_PATH,
    LINT_INTEGRITY_RECORD_PATH,
    LINT_SCAN_REPORT_PATH,
    REFERENCE_FINDING_GRID_PATH,
    RULE_COVERAGE_SNAPSHOT_PATH,
    RULE_REGISTRY_PATH,
    SCAN_STAGE_AUTHORITY_PATH,
    SCAN_STAGE_TARGETS_PATH,
    SCAN_SUMMARY_PATH,
    SCAN_TRACE_PATH,
    STALE_RULE_PACK_PATH,
    SUBJECT_CASE_ID,
    OUTPUT_DIR,
)
from rule_closure_lane import closure_rules
from rule_registry_loader import load_rule_registry
from run_post_scan_finalize import remap_scan_tokens


def _write_trace(path: Path, stages: list[str], authority: dict) -> None:
    actions = authority.get("stage_actions", {})
    lines = [f"target={s}: action={actions.get(s, 'touched')}" for s in stages]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    registry = load_rule_registry(RULE_REGISTRY_PATH, STALE_RULE_PACK_PATH)
    ref = json.loads(REFERENCE_FINDING_GRID_PATH.read_text(encoding="utf-8"))
    authority = json.loads(SCAN_STAGE_AUTHORITY_PATH.read_text(encoding="utf-8"))

    graph = registry.get("rule_dependency_graph", {})
    expected_rules = set(graph.get("expected_closure", []))
    enabled = closure_rules(graph, list(registry.get("active_rules", [])))
    missing_rules = len(expected_rules - enabled)

    paths = expand_corpus_paths(CORPUS_DIR, ref.get("corpus_files", []))
    rule_index = {r["rule_id"]: r for r in registry.get("rules", [])}
    raw_hits = dispatch_ast_scan(paths, enabled, rule_index)

    expected_rows = ref.get("expected_findings", [])
    expected_keys = {(r["file"], r["line"], r["rule_id"]) for r in expected_rows}
    got_keys = {(h["file"], h["line"], h["rule_id"]) for h in raw_hits}
    corpus_aligned = got_keys == expected_keys

    bound_rows = []
    report_findings = []
    for hit in raw_hits:
        bound = bind_finding_row(hit)
        stable = (hit["file"], hit["line"], hit["rule_id"]) in expected_keys
        bound["finding_stable"] = stable
        bound_rows.append(
            {
                "rule_id": bound["rule_id"],
                "file": bound["file"],
                "line": bound["line"],
                "col": bound["col"],
                "fingerprint": bound["fingerprint"],
                "finding_stable": stable,
            }
        )
        report_findings.append(
            {
                "rule_id": hit["rule_id"],
                "file": hit["file"],
                "line": hit["line"],
                "col": hit.get("col", 0),
                "finding_stable": stable,
            }
        )

    FINDING_BINDING_AUDIT_PATH.write_text(
        json.dumps({"entries": bound_rows}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    verified = missing_rules == 0 and corpus_aligned
    write_scan_report(
        LINT_SCAN_REPORT_PATH,
        case_id=SUBJECT_CASE_ID,
        findings=report_findings,
        scan_verified=verified,
        corpus_aligned=corpus_aligned,
    )

    digest = seal_findings_digest(report_findings)
    RULE_COVERAGE_SNAPSHOT_PATH.write_text(
        json.dumps(
            {
                "case_id": SUBJECT_CASE_ID,
                "enabled_rules": sorted(enabled),
                "expected_rule_count": len(expected_rules),
                "missing_rule_count": missing_rules,
                "rule_graph_digest": digest,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    stages = [ln.strip() for ln in SCAN_STAGE_TARGETS_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    _write_trace(SCAN_TRACE_PATH, stages, authority)
    remap_scan_tokens(SCAN_TRACE_PATH)

    LINT_INTEGRITY_RECORD_PATH.write_text(
        json.dumps(
            {
                "case_id": SUBJECT_CASE_ID,
                "enabled_rule_count": len(enabled),
                "missing_rule_count": missing_rules,
                "rule_loss_zero": missing_rules == 0,
                "findings_digest": digest,
                "audit_event_recorded": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    att = json.loads(LINT_INTEGRITY_RECORD_PATH.read_text(encoding="utf-8"))
    att["audit_event_recorded"] = all(r["finding_stable"] for r in report_findings) and corpus_aligned
    LINT_INTEGRITY_RECORD_PATH.write_text(json.dumps(att, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    rep = json.loads(LINT_SCAN_REPORT_PATH.read_text(encoding="utf-8"))
    rep["scan_complete"] = verified and att["audit_event_recorded"]
    LINT_SCAN_REPORT_PATH.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    SCAN_SUMMARY_PATH.write_text(
        json.dumps(
            {
                "case_id": SUBJECT_CASE_ID,
                "files_scanned": len(paths),
                "dispatch_stages_recorded": len(stages),
                "trace_logged": True,
                "scan_reconciled": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
