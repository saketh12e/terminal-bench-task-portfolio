import hashlib
import json
from pathlib import Path


def finalize_runtime_outputs(output_dir):
    # Broken behavior: a stale deployment hook rewrites report fields after the
    # runtime writer has produced otherwise plausible artifacts.
    output_dir = Path(output_dir)
    report_path = output_dir / "evaluation_report.json"
    if not report_path.exists():
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    audit_path = output_dir / "token_score_audit.csv"
    if audit_path.exists():
        report["audit_sha256"] = hashlib.sha256(audit_path.read_bytes()).hexdigest()
    report["calibration_current_count"] = 0
    report["calibration_adjustment_count"] = 0
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
