from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import (
    APP_DIR,
    CORPUS_DIR,
    FINDING_BINDING_AUDIT_PATH,
    FINDING_BINDING_POLICY_PATH,
    LINT_INTEGRITY_RECORD_PATH,
    LINT_SCAN_REPORT_PATH,
    PYTHON_BIN,
    REFERENCE_FINDING_GRID_PATH,
    RULE_COVERAGE_SNAPSHOT_PATH,
    RULE_REGISTRY_PATH,
    SCAN_STAGE_AUTHORITY_PATH,
    SCAN_STAGE_TARGETS_PATH,
    SCAN_SUMMARY_PATH,
    SCAN_TRACE_PATH,
    STALE_RULE_PACK_PATH,
    SUBJECT_CASE_ID,
    WORK_LINT_POLICY_PATH,
    load_json,
    run_pipeline,
)

sys.path.insert(0, str(APP_DIR))
from integrity_digest_seal import seal_findings_digest  # noqa: E402
from lint_scan_physics import live_findings, rule_closure  # noqa: E402


def report() -> dict:
    return load_json(LINT_SCAN_REPORT_PATH)


def coverage() -> dict:
    return load_json(RULE_COVERAGE_SNAPSHOT_PATH)


def integrity() -> dict:
    return load_json(LINT_INTEGRITY_RECORD_PATH)


def test_runner_exit_zero():
    proc = subprocess.run(
        [PYTHON_BIN, "lint_policy_runner.py"],
        cwd=APP_DIR,
        env={**__import__("os").environ, "PYTHONPATH": str(APP_DIR)},
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0


def test_lint_scan_report_exists():
    assert LINT_SCAN_REPORT_PATH.is_file()


def test_coverage_snapshot_exists():
    assert RULE_COVERAGE_SNAPSHOT_PATH.is_file()


def test_binding_audit_exists():
    assert FINDING_BINDING_AUDIT_PATH.is_file()


def test_integrity_record_exists():
    assert LINT_INTEGRITY_RECORD_PATH.is_file()


def test_summary_exists():
    assert SCAN_SUMMARY_PATH.is_file()


def test_trace_exists():
    assert SCAN_TRACE_PATH.is_file()


def test_case_id_report():
    assert report()["case_id"] == SUBJECT_CASE_ID


def test_finding_count_matches_reference():
    ref = load_json(REFERENCE_FINDING_GRID_PATH)
    assert report()["finding_count"] == len(ref["expected_findings"])


def test_missing_rule_count_zero():
    assert coverage()["missing_rule_count"] == 0


def test_enabled_rules_include_r005():
    assert "R005" in coverage()["enabled_rules"]


def test_coverage_rule_count_matches_expected():
    ref = load_json(REFERENCE_FINDING_GRID_PATH)
    expected = len(ref["rule_dependency_graph"]["expected_closure"])
    assert coverage()["expected_rule_count"] == expected
    assert len(coverage()["enabled_rules"]) == expected


def test_report_findings_match_reference_set():
    ref = set(
        (r["file"], r["line"], r["rule_id"])
        for r in load_json(REFERENCE_FINDING_GRID_PATH)["expected_findings"]
    )
    got = {(r["file"], r["line"], r["rule_id"]) for r in report()["findings"]}
    assert got == ref


def test_corpus_aligned_flag():
    assert report()["corpus_aligned"] is True


def test_files_scanned_all_manifest_entries():
    ref = load_json(REFERENCE_FINDING_GRID_PATH)
    assert load_json(SCAN_SUMMARY_PATH)["files_scanned"] == len(ref["corpus_files"])


def test_finding_fingerprints_match_live_binding():
    policy = load_json(FINDING_BINDING_POLICY_PATH)
    registry = load_json(RULE_REGISTRY_PATH)
    live = live_findings(CORPUS_DIR, registry, policy)
    live_fp = {(r["file"], r["line"], r["rule_id"]): r["fingerprint"] for r in live}
    audit = load_json(FINDING_BINDING_AUDIT_PATH)
    for entry in audit["entries"]:
        key = (entry["file"], entry["line"], entry["rule_id"])
        assert entry["fingerprint"] == live_fp[key]


def test_all_findings_stable_when_aligned():
    for row in report()["findings"]:
        assert row["finding_stable"] is True


def test_audit_stable_matches_report():
    audit = {
        (e["file"], e["line"], e["rule_id"]): e
        for e in load_json(FINDING_BINDING_AUDIT_PATH)["entries"]
    }
    for row in report()["findings"]:
        key = (row["file"], row["line"], row["rule_id"])
        assert audit[key]["finding_stable"] == row["finding_stable"]


def test_findings_digest_matches_integrity():
    digest = seal_findings_digest(report()["findings"])
    assert integrity()["findings_digest"] == digest


def test_coverage_rule_graph_digest_matches_sealed():
    digest = seal_findings_digest(report()["findings"])
    assert coverage()["rule_graph_digest"] == digest


def test_digest_not_filename_only_weak_form():
    weak = hashlib.sha256("|".join(sorted(r["file"] for r in report()["findings"])).encode()).hexdigest()
    assert integrity()["findings_digest"] != weak


def test_coverage_has_rule_graph_digest_not_weak():
    cov = coverage()
    assert "rule_graph_digest" in cov
    assert "weak_digest" not in cov


def test_scan_verified_requires_zero_missing_rules():
    assert report()["scan_verified"] == (coverage()["missing_rule_count"] == 0)


def test_rule_loss_zero_matches_missing():
    assert integrity()["rule_loss_zero"] == (coverage()["missing_rule_count"] == 0)


def test_scan_complete_requires_verified_and_audit():
    rep = report()
    if coverage()["missing_rule_count"] != 0 or not rep["corpus_aligned"]:
        assert rep["scan_complete"] is False
    else:
        assert rep["scan_complete"] is True


def test_integrity_audit_event_recorded():
    assert integrity()["audit_event_recorded"] is True
    assert integrity()["findings_digest"] == seal_findings_digest(report()["findings"])


def test_overlay_cannot_mark_complete_with_missing_rules():
    if coverage()["missing_rule_count"] > 0:
        assert report()["scan_complete"] is False


def test_work_policy_seeded():
    assert WORK_LINT_POLICY_PATH.is_file()


def test_stage_log_line_count():
    lines = [ln for ln in SCAN_TRACE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 5


def test_stage_log_authority_tokens():
    authority = load_json(SCAN_STAGE_AUTHORITY_PATH)["stage_actions"]
    for line in SCAN_TRACE_PATH.read_text(encoding="utf-8").splitlines():
        if ": action=" not in line:
            continue
        stage = line.split("target=", 1)[1].split(":", 1)[0].strip()
        token = line.split("action=", 1)[1].strip()
        assert token == authority[stage]


def test_stage_log_no_touched_tokens():
    assert "action=touched" not in SCAN_TRACE_PATH.read_text(encoding="utf-8")


def test_expand_corpus_stage_token():
    text = SCAN_TRACE_PATH.read_text(encoding="utf-8")
    assert "target=expand_corpus_manifest: action=resolve_corpus_paths" in text


def test_seal_closeout_stage_token():
    text = SCAN_TRACE_PATH.read_text(encoding="utf-8")
    assert "target=seal_rule_closeout: action=seal_integrity_record" in text


def test_summary_scan_reconciled_true():
    assert load_json(SCAN_SUMMARY_PATH)["scan_reconciled"] is True


def test_summary_trace_logged():
    assert load_json(SCAN_SUMMARY_PATH)["trace_logged"] is True


def test_summary_dispatch_stages():
    targets = [ln.strip() for ln in SCAN_STAGE_TARGETS_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert load_json(SCAN_SUMMARY_PATH)["dispatch_stages_recorded"] == len(targets)


def test_stale_pack_differs_from_registry():
    stale = load_json(STALE_RULE_PACK_PATH)
    reg = load_json(RULE_REGISTRY_PATH)
    assert stale["active_rules"] != reg["active_rules"]


def test_findings_include_pickle_rule():
    rules = {r["rule_id"] for r in report()["findings"]}
    assert "R005" in rules


def test_findings_include_eval_rule():
    rules = {r["rule_id"] for r in report()["findings"]}
    assert "R002" in rules


def test_clean_module_has_no_findings():
    files = {r["file"] for r in report()["findings"]}
    assert "clean_module.py" not in files


def test_second_run_stable_digest():
    d1 = seal_findings_digest(report()["findings"])
    run_pipeline()
    d2 = seal_findings_digest(load_json(LINT_SCAN_REPORT_PATH)["findings"])
    assert d1 == d2


def test_post_finalize_does_not_force_complete_with_bad_corpus():
    rep = report()
    ref = load_json(REFERENCE_FINDING_GRID_PATH)
    expected = {(r["file"], r["line"], r["rule_id"]) for r in ref["expected_findings"]}
    got = {(r["file"], r["line"], r["rule_id"]) for r in rep["findings"]}
    if got != expected:
        assert rep["scan_complete"] is False


def test_finding_stable_false_when_fingerprint_wrong():
    audit = load_json(FINDING_BINDING_AUDIT_PATH)
    policy = load_json(FINDING_BINDING_POLICY_PATH)
    registry = load_json(RULE_REGISTRY_PATH)
    live = live_findings(CORPUS_DIR, registry, policy)
    live_fp = {(r["file"], r["line"], r["rule_id"]): r["fingerprint"] for r in live}
    for entry in audit["entries"]:
        if entry["fingerprint"] != live_fp[(entry["file"], entry["line"], entry["rule_id"])]:
            assert entry["finding_stable"] is False


def test_registry_path_in_data_dir():
    assert RULE_REGISTRY_PATH.is_file()


def test_reference_grid_path_in_data_dir():
    assert REFERENCE_FINDING_GRID_PATH.is_file()


def test_corpus_has_six_modules():
    assert len(list(CORPUS_DIR.glob("*.py"))) == 6


def test_enabled_rule_count_integrity():
    assert integrity()["enabled_rule_count"] == len(coverage()["enabled_rules"])


def test_missing_rule_count_integrity_matches_coverage():
    assert integrity()["missing_rule_count"] == coverage()["missing_rule_count"]


def test_scan_verified_true_on_success():
    assert report()["scan_verified"] is True


def test_rule_graph_closure_physics():
    registry = load_json(RULE_REGISTRY_PATH)
    graph = registry["rule_dependency_graph"]
    live = rule_closure(graph, registry["active_rules"])
    assert live == set(graph["expected_closure"])


def test_digest_changes_when_rule_id_tampered():
    base = seal_findings_digest(report()["findings"])
    tampered = json.loads(json.dumps(report()["findings"]))
    tampered[0]["rule_id"] = "R999"
    assert seal_findings_digest(tampered) != base


def test_binding_policy_segment_names_present():
    pol = load_json(FINDING_BINDING_POLICY_PATH)
    assert pol["segment_names"] == ["rule_id", "file", "line", "col"]


def test_report_includes_col_field():
    for row in report()["findings"]:
        assert "col" in row


def test_audit_entries_count_matches_findings():
    assert len(load_json(FINDING_BINDING_AUDIT_PATH)["entries"]) == report()["finding_count"]


def test_missing_rule_count_nonzero_on_broken_closure():
    assert coverage()["missing_rule_count"] == 0


def test_scan_reconciled_requires_full_pipeline():
    assert load_json(SCAN_SUMMARY_PATH)["scan_reconciled"] is True


def test_rule_graph_digest_present_in_coverage():
    assert isinstance(coverage().get("rule_graph_digest"), str)
    assert len(coverage()["rule_graph_digest"]) == 64


def test_finding_count_at_least_five():
    assert report()["finding_count"] >= 5


def test_auth_utils_bare_except_finding():
    hits = [r for r in report()["findings"] if r["file"] == "auth_utils.py" and r["rule_id"] == "R001"]
    assert len(hits) == 1


def test_pickle_risk_finding_present():
    hits = [r for r in report()["findings"] if r["file"] == "pickle_risk.py"]
    assert len(hits) >= 1


def test_config_loader_mutable_default_finding():
    hits = [r for r in report()["findings"] if r["file"] == "config_loader.py" and r["rule_id"] == "R004"]
    assert len(hits) == 1


def test_integrity_enabled_rule_count_matches_coverage():
    assert integrity()["enabled_rule_count"] == len(coverage()["enabled_rules"])


def test_scan_complete_true_when_all_layers_align():
    assert report()["scan_complete"] is True


def test_coverage_snapshot_must_not_publish_weak_digest():
    assert "weak_digest" not in coverage()


def test_enabled_rules_count_exactly_five():
    assert len(coverage()["enabled_rules"]) == 5


def test_finding_count_exactly_five():
    assert report()["finding_count"] == 5


def test_worker_file_has_secret_literal_finding():
    assert any(r["file"] == "worker.py" and r["rule_id"] == "R003" for r in report()["findings"])


def test_api_handler_eval_finding_line_three():
    row = next(r for r in report()["findings"] if r["file"] == "api_handler.py" and r["rule_id"] == "R002")
    assert row["line"] == 3


def test_integrity_findings_digest_hex_length():
    assert len(integrity()["findings_digest"]) == 64


def test_scan_summary_files_scanned_six():
    assert load_json(SCAN_SUMMARY_PATH)["files_scanned"] == 6


def test_rule_loss_zero_true():
    assert integrity()["rule_loss_zero"] is True


def test_scan_verified_true():
    assert report()["scan_verified"] is True


def test_compile_ast_visit_stage_token():
    assert "target=compile_ast_visit_plan: action=sync_ast_visitors" in SCAN_TRACE_PATH.read_text(encoding="utf-8")


def test_publish_scan_report_stage_token():
    assert "target=publish_lint_scan_report: action=publish_scan_report" in SCAN_TRACE_PATH.read_text(encoding="utf-8")


def test_binding_audit_fingerprint_hex_length():
    for entry in load_json(FINDING_BINDING_AUDIT_PATH)["entries"]:
        assert len(entry["fingerprint"]) == 16


def test_all_expected_rules_in_enabled_list():
    ref = load_json(REFERENCE_FINDING_GRID_PATH)
    expected = set(ref["rule_dependency_graph"]["expected_closure"])
    assert set(coverage()["enabled_rules"]) == expected


def test_emit_binding_audit_stage_token():
    assert "target=emit_finding_binding_audit: action=write_binding_audit" in SCAN_TRACE_PATH.read_text(encoding="utf-8")


def test_r002_and_r004_enabled_in_coverage():
    rules = set(coverage()["enabled_rules"])
    assert {"R002", "R004"}.issubset(rules)


def test_findings_cover_auth_and_pickle_files():
    files = {r["file"] for r in report()["findings"]}
    assert "auth_utils.py" in files
    assert "pickle_risk.py" in files


def test_integrity_and_coverage_digest_equal():
    assert integrity()["findings_digest"] == coverage()["rule_graph_digest"]


def test_scan_complete_and_reconciled_together():
    assert report()["scan_complete"] is True
    assert load_json(SCAN_SUMMARY_PATH)["scan_reconciled"] is True


def test_live_physics_row_count_matches_report():
    policy = load_json(FINDING_BINDING_POLICY_PATH)
    registry = load_json(RULE_REGISTRY_PATH)
    live = live_findings(CORPUS_DIR, registry, policy)
    assert len(live) == report()["finding_count"]


def test_reference_expected_finding_count_five():
    ref = load_json(REFERENCE_FINDING_GRID_PATH)
    assert len(ref["expected_findings"]) == 5


def test_all_rule_ids_r001_through_r005_enabled():
    enabled = set(coverage()["enabled_rules"])
    for rid in ("R001", "R002", "R003", "R004", "R005"):
        assert rid in enabled


def test_expected_rule_count_field_equals_five():
    assert coverage()["expected_rule_count"] == 5


def test_corpus_aligned_implies_matching_reference():
    if report()["corpus_aligned"]:
        ref = load_json(REFERENCE_FINDING_GRID_PATH)
        expected = {(r["file"], r["line"], r["rule_id"]) for r in ref["expected_findings"]}
        got = {(r["file"], r["line"], r["rule_id"]) for r in report()["findings"]}
        assert got == expected
