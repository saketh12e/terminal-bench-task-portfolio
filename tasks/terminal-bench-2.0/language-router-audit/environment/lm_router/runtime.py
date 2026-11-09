import csv
import hashlib
import json
from pathlib import Path

from lm_router.calibration import calibration_events_sha256
from lm_router.scorer import score_batch


RUNTIME_AUDIT_FIELDS = [
    "input_id",
    "label_id",
    "variant_index",
    "row_type",
    "position",
    "token_id",
    "token",
    "prev_token_id",
    "base_micro",
    "transition_micro",
    "included_in_score",
    "running_raw_micro",
    "policy_rule_ids",
    "policy_adjustment_micro",
    "calibration_event_ids",
    "calibration_adjustment_micro",
    "runtime_adjusted_micro",
]


def load_runtime_policy(policy_path="/app/model/router_runtime_policy.json"):
    return json.loads(Path(policy_path).read_text(encoding="utf-8"))


def select_runtime_policy(policy, served_at):
    # Broken behavior: ignores the request timestamp and keeps every policy rule.
    return policy


def runtime_policy_sha256(policy_path="/app/model/router_runtime_policy.json"):
    return hashlib.sha256(Path(policy_path).read_bytes()).hexdigest()


def apply_runtime_policy(message_tokens, candidate, policy, calibration=None):
    # Broken behavior: the serving path preserves base scorer order and ignores
    # the runtime calibration rules.
    variants = []
    for variant in candidate.get("variants", [candidate]):
        row = dict(variant)
        row["policy_rule_ids"] = []
        row["policy_adjustment_micro"] = 0
        row["calibration_event_ids"] = []
        row["calibration_adjustment_micro"] = 0
        row["runtime_adjusted_micro"] = row["adjusted_micro"]
        variants.append(row)
    best = dict(variants[0])
    best["variants"] = variants
    return best


def score_runtime_batch(
    batch_path,
    router,
    policy,
    policy_path="/app/model/router_runtime_policy.json",
    calibration=None,
    calibration_path="/app/model/calibration_events.jsonl",
):
    predictions, audit_rows, report = score_batch(batch_path, router)
    for prediction in predictions:
        for score in prediction["label_scores"]:
            score["policy_rule_ids"] = []
            score["policy_adjustment_micro"] = 0
            score["calibration_event_ids"] = []
            score["calibration_adjustment_micro"] = 0
            score["runtime_adjusted_micro"] = score["adjusted_micro"]
    for row in audit_rows:
        row["policy_rule_ids"] = ""
        row["policy_adjustment_micro"] = "0" if row["row_type"] == "candidate" else ""
        row["calibration_event_ids"] = ""
        row["calibration_adjustment_micro"] = "0" if row["row_type"] == "candidate" else ""
        row["runtime_adjusted_micro"] = "0" if row["row_type"] == "candidate" else ""
    report["runtime_policy_id"] = policy["policy_id"]
    report["runtime_policy_sha256"] = runtime_policy_sha256(policy_path)
    report["calibration_events_sha256"] = calibration_events_sha256(calibration_path)
    report["calibration_current_count"] = 0
    report["calibration_adjustment_count"] = 0
    report["policy_adjustment_count"] = 0
    return predictions, audit_rows, report


def write_runtime_outputs(predictions, audit_rows, report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    with (output_dir / "token_score_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUNTIME_AUDIT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(audit_rows)
    (output_dir / "evaluation_report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
