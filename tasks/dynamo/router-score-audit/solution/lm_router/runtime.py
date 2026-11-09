import csv
import hashlib
import json
from pathlib import Path

from lm_router.calibration import _parse_time, calibration_events_sha256, select_calibration_events
from lm_router.scorer import _digest_rows, _half_even_div, _read_jsonl, score_candidate, tokenize_text


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
    served_time = _parse_time(served_at)
    selected = dict(policy)
    rules = []
    for rule in policy.get("rules", []):
        if _parse_time(rule["effective_from"]) > served_time:
            continue
        expires_at = rule.get("expires_at")
        if expires_at is not None and served_time >= _parse_time(expires_at):
            continue
        rules.append(dict(rule))
    selected["rules"] = rules
    return selected


def runtime_policy_sha256(policy_path="/app/model/router_runtime_policy.json"):
    return hashlib.sha256(Path(policy_path).read_bytes()).hexdigest()


def _rule_matches(rule, prompt_token_ids, label_id, variant_index):
    if rule["target_label"] != label_id:
        return False
    if int(rule["target_variant_index"]) != int(variant_index):
        return False
    prompt_set = {int(token_id) for token_id in prompt_token_ids}
    all_ids = {int(token_id) for token_id in rule.get("if_all_prompt_token_ids", [])}
    any_ids = {int(token_id) for token_id in rule.get("if_any_prompt_token_ids", [])}
    no_ids = {int(token_id) for token_id in rule.get("if_no_prompt_token_ids", [])}
    if not all_ids.issubset(prompt_set):
        return False
    if any_ids and not (prompt_set & any_ids):
        return False
    if prompt_set & no_ids:
        return False
    return True


def _event_matches(event, prompt_token_ids, label_id, variant_index):
    if event["target_label"] != label_id:
        return False
    if int(event["target_variant_index"]) != int(variant_index):
        return False
    prompt_set = {int(token_id) for token_id in prompt_token_ids}
    required = {int(token_id) for token_id in event.get("required_prompt_token_ids", [])}
    any_ids = {int(token_id) for token_id in event.get("any_prompt_token_ids", [])}
    blocked = {int(token_id) for token_id in event.get("blocked_prompt_token_ids", [])}
    if not required.issubset(prompt_set):
        return False
    if any_ids and not (prompt_set & any_ids):
        return False
    if prompt_set & blocked:
        return False
    return True


def _decorate_variant(variant, prompt_token_ids, policy, calibration=None):
    matched = [
        rule
        for rule in policy["rules"]
        if _rule_matches(rule, prompt_token_ids, variant["label_id"], variant["variant_index"])
    ]
    policy_adjustment = sum(int(rule["adjustment_micro"]) for rule in matched)
    calibration_matches = [
        event
        for event in (calibration or {}).get("events", [])
        if _event_matches(event, prompt_token_ids, variant["label_id"], variant["variant_index"])
    ]
    calibration_adjustment = sum(int(event["adjustment_micro"]) for event in calibration_matches)
    row = dict(variant)
    row["policy_rule_ids"] = [rule["rule_id"] for rule in matched]
    row["policy_adjustment_micro"] = policy_adjustment
    row["calibration_event_ids"] = [event["event_id"] for event in calibration_matches]
    row["calibration_adjustment_micro"] = calibration_adjustment
    row["runtime_adjusted_micro"] = int(row["adjusted_micro"]) + policy_adjustment + calibration_adjustment
    return row


def apply_runtime_policy(message_tokens, candidate, policy, calibration=None):
    prompt_token_ids = [token["token_id"] for token in message_tokens]
    variants = [
        _decorate_variant(variant, prompt_token_ids, policy, calibration)
        for variant in candidate["variants"]
    ]
    variants.sort(
        key=lambda row: (
            -row["runtime_adjusted_micro"],
            -row["adjusted_micro"],
            -row["normalized_micro"],
            -row["raw_micro"],
            row["variant_index"],
        )
    )
    best = dict(variants[0])
    best["variants"] = variants
    return best


def _rank_runtime(scored, router):
    order = router["label_order"]
    return sorted(
        scored,
        key=lambda row: (
            -row["runtime_adjusted_micro"],
            -row["adjusted_micro"],
            -row["normalized_micro"],
            -row["raw_micro"],
            order[row["label_id"]],
        ),
    )


def _canonical_digest(value):
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _unique_in_order(values):
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def build_serving_trace(predictions, audit_rows, trace_contexts):
    audit_by_input = {}
    for row in audit_rows:
        audit_by_input.setdefault(row["input_id"], []).append(row)

    rows = []
    for prediction in sorted(predictions, key=lambda row: row["input_id"]):
        input_id = prediction["input_id"]
        context = trace_contexts[input_id]
        policy_ids = _unique_in_order(
            rule_id
            for score in prediction["label_scores"]
            for rule_id in score["policy_rule_ids"]
        )
        calibration_ids = _unique_in_order(
            event_id
            for score in prediction["label_scores"]
            for event_id in score["calibration_event_ids"]
        )
        partial = {
            "input_id": input_id,
            "served_at": context["served_at"],
            "top_label": prediction["top_label"],
            "predicted_label": prediction["predicted_label"],
            "abstained": prediction["abstained"],
            "policy_snapshot_rule_count": len(context["policy_rules"]),
            "calibration_snapshot_event_count": len(context["calibration_events"]),
            "policy_rule_ids": policy_ids,
            "calibration_event_ids": calibration_ids,
            "policy_snapshot_sha256": _canonical_digest(context["policy_rules"]),
            "calibration_snapshot_sha256": _canonical_digest(context["calibration_events"]),
            "score_vector_sha256": _canonical_digest(prediction["label_scores"]),
            "audit_span_sha256": _canonical_digest(audit_by_input.get(input_id, [])),
            "selected_variant_signature": "|".join(
                f"{score['label_id']}:{score['variant_index']}:{score['runtime_adjusted_micro']}"
                for score in prediction["label_scores"]
            ),
        }
        row = dict(partial)
        row["lineage_sha256"] = _canonical_digest(partial)
        rows.append(row)
    return rows


def score_runtime_batch(
    batch_path,
    router,
    policy,
    policy_path="/app/model/router_runtime_policy.json",
    calibration=None,
    calibration_path="/app/model/calibration_events.jsonl",
):
    config = router["config"]
    predictions = []
    audit_rows = []
    correct = 0
    labeled = 0
    margins = []
    policy_adjustment_count = 0
    calibration_adjustment_count = 0
    trace_contexts = {}
    calibration = calibration or {"events": []}
    batch_rows = _read_jsonl(batch_path)
    latest_served_at = max((row["served_at"] for row in batch_rows), default="1970-01-01T00:00:00Z")
    latest_calibration = select_calibration_events(calibration, latest_served_at)

    for item in batch_rows:
        input_id = item["input_id"]
        message_tokens = tokenize_text(item["text"], router)
        item_policy = select_runtime_policy(policy, item["served_at"])
        item_calibration = select_calibration_events(calibration, item["served_at"])
        trace_contexts[input_id] = {
            "served_at": item["served_at"],
            "policy_rules": item_policy["rules"],
            "calibration_events": item_calibration["events"],
        }
        for token in message_tokens:
            audit_rows.append(
                {
                    "input_id": input_id,
                    "label_id": "",
                    "variant_index": "",
                    "row_type": "prompt",
                    "position": str(token["position"]),
                    "token_id": str(token["token_id"]),
                    "token": token["token"],
                    "prev_token_id": "",
                    "base_micro": "0",
                    "transition_micro": "0",
                    "included_in_score": "false",
                    "running_raw_micro": "",
                    "policy_rule_ids": "",
                    "policy_adjustment_micro": "",
                    "calibration_event_ids": "",
                    "calibration_adjustment_micro": "",
                    "runtime_adjusted_micro": "",
                }
            )

        base_scored = [score_candidate(message_tokens, label, router) for label in config["labels"]]
        scored = _rank_runtime(
            [apply_runtime_policy(message_tokens, row, item_policy, item_calibration) for row in base_scored],
            router,
        )
        top, runner_up = scored[0], scored[1]
        margin = top["runtime_adjusted_micro"] - runner_up["runtime_adjusted_micro"]
        abstained = margin <= int(config["abstain_margin_micro"])
        predicted = config["abstain_label"] if abstained else top["label_id"]

        for candidate in scored:
            for variant in candidate["variants"]:
                if variant["policy_adjustment_micro"] != 0:
                    policy_adjustment_count += 1
                if variant["calibration_adjustment_micro"] != 0:
                    calibration_adjustment_count += 1
                for token in variant["tokens"]:
                    audit_rows.append(
                        {
                            "input_id": input_id,
                            "label_id": candidate["label_id"],
                            "variant_index": str(variant["variant_index"]),
                            "row_type": "candidate",
                            "position": str(token["position"]),
                            "token_id": str(token["token_id"]),
                            "token": token["token"],
                            "prev_token_id": str(token["prev_token_id"]),
                            "base_micro": str(token["base_micro"]),
                            "transition_micro": str(token["transition_micro"]),
                            "included_in_score": "true",
                            "running_raw_micro": str(token["running_raw_micro"]),
                            "policy_rule_ids": "|".join(variant["policy_rule_ids"]),
                            "policy_adjustment_micro": str(variant["policy_adjustment_micro"]),
                            "calibration_event_ids": "|".join(variant["calibration_event_ids"]),
                            "calibration_adjustment_micro": str(variant["calibration_adjustment_micro"]),
                            "runtime_adjusted_micro": str(variant["runtime_adjusted_micro"]),
                        }
                    )

        label_scores = [
            {
                "label_id": row["label_id"],
                "variant_index": row["variant_index"],
                "verbalizer": row["verbalizer"],
                "raw_micro": row["raw_micro"],
                "token_count": row["token_count"],
                "normalized_micro": row["normalized_micro"],
                "prior_micro": row["prior_micro"],
                "adjusted_micro": row["adjusted_micro"],
                "policy_rule_ids": row["policy_rule_ids"],
                "policy_adjustment_micro": row["policy_adjustment_micro"],
                "calibration_event_ids": row["calibration_event_ids"],
                "calibration_adjustment_micro": row["calibration_adjustment_micro"],
                "runtime_adjusted_micro": row["runtime_adjusted_micro"],
            }
            for row in scored
        ]
        predictions.append(
            {
                "input_id": input_id,
                "predicted_label": predicted,
                "top_label": top["label_id"],
                "runner_up_label": runner_up["label_id"],
                "abstained": abstained,
                "margin_micro": margin,
                "label_scores": label_scores,
            }
        )
        gold_label = item.get("gold_label")
        if isinstance(gold_label, str) and gold_label != "":
            labeled += 1
            if predicted == gold_label:
                correct += 1
        margins.append(margin)

    predictions.sort(key=lambda row: row["input_id"])
    audit_rows.sort(
        key=lambda row: (
            row["input_id"],
            row["row_type"],
            row["label_id"],
            int(row["variant_index"] or -1),
            int(row["position"]),
        )
    )
    serving_trace = build_serving_trace(predictions, audit_rows, trace_contexts)
    report = {
        "schema_version": "router-eval-v1",
        "runtime_policy_id": policy["policy_id"],
        "runtime_policy_sha256": runtime_policy_sha256(policy_path),
        "calibration_events_sha256": calibration_events_sha256(calibration_path),
        "calibration_current_count": len(latest_calibration.get("events", [])),
        "calibration_adjustment_count": calibration_adjustment_count,
        "prediction_count": len(predictions),
        "label_count": len(config["labels"]),
        "abstention_count": sum(1 for row in predictions if row["abstained"]),
        "audit_row_count": len(audit_rows),
        "policy_adjustment_count": policy_adjustment_count,
        "labeled_count": labeled,
        "correct_labeled_count": correct,
        "accuracy_micro": 0 if labeled == 0 else _half_even_div(correct * 1_000_000, labeled),
        "mean_margin_micro": _half_even_div(sum(margins), max(1, len(margins))),
        "predictions_sha256": _digest_rows(predictions),
        "audit_sha256": _digest_rows(audit_rows),
        "serving_trace_count": len(serving_trace),
        "serving_trace_sha256": _digest_rows(serving_trace),
    }
    return predictions, audit_rows, serving_trace, report


def write_runtime_outputs(predictions, audit_rows, serving_trace, report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    with (output_dir / "token_score_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RUNTIME_AUDIT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(audit_rows)
    with (output_dir / "serving_trace.jsonl").open("w", encoding="utf-8") as handle:
        for row in serving_trace:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    (output_dir / "evaluation_report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
