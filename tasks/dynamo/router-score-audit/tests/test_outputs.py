import csv
import hashlib
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


APP = Path(os.environ.get("ROUTER_APP_ROOT", "/app"))
OUTPUT = APP / "output"
VISIBLE_BATCH = APP / "data" / "eval_batch.jsonl"
CONFIG = APP / "data" / "router_config.json"
TOKENIZER = APP / "model" / "tokenizer.json"
SCORES = APP / "model" / "token_scores.json"
POLICY = APP / "model" / "router_runtime_policy.json"
CALIBRATION = APP / "model" / "calibration_events.jsonl"
TEST_ROOT = Path(os.environ.get("ROUTER_TEST_ROOT", "/tests"))
HIDDEN_BATCH = TEST_ROOT / "fixtures" / "hidden" / "eval_batch_hidden.jsonl"

PREDICTIONS_PATH = OUTPUT / "predictions.jsonl"
AUDIT_PATH = OUTPUT / "token_score_audit.csv"
TRACE_PATH = OUTPUT / "serving_trace.jsonl"
REPORT_PATH = OUTPUT / "evaluation_report.json"

EXPECTED_INPUT_SHA256 = {
    "data/eval_batch.jsonl": "791d01f269ae1d5e5011564a99ee0960a357616266e4f087fb19eaa08e22996a",
    "data/router_config.json": "22ac41a98fc36b4cfb90ab6e5e2d1510d1e23d634714c34336ca191dce73c8b5",
    "model/tokenizer.json": "d9de014eeea80eed0ee964d0714f163fd3c448a126ec4ee5a1b35eda884f8180",
    "model/token_scores.json": "c082c037538e4f88e097b7043cc4ff879b2631c60b2039b1e0f1748e8c5b4b5b",
    "model/router_runtime_policy.json": "d049b437e972bdc44888a2655c5be75e27158f32f7b2729a673910c243b6e6f2",
    "model/calibration_events.jsonl": "c08d0839f1e491a5ae08dc75feebf105ae5950ccfc88db5a4f30a39813107beb",
}

AUDIT_FIELDS = [
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

TRACE_FIELDS = {
    "input_id",
    "served_at",
    "top_label",
    "predicted_label",
    "abstained",
    "policy_snapshot_rule_count",
    "calibration_snapshot_event_count",
    "policy_rule_ids",
    "calibration_event_ids",
    "policy_snapshot_sha256",
    "calibration_snapshot_sha256",
    "score_vector_sha256",
    "audit_span_sha256",
    "selected_variant_signature",
    "lineage_sha256",
}


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == AUDIT_FIELDS
        return list(reader)


def read_report(path=REPORT_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_router(config_path=CONFIG, tokenizer_path=TOKENIZER, scores_path=SCORES):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    tokenizer = json.loads(Path(tokenizer_path).read_text(encoding="utf-8"))
    scores = json.loads(Path(scores_path).read_text(encoding="utf-8"))
    return {
        "config": config,
        "tokenizer": tokenizer,
        "scores": scores,
        "label_order": {label["label_id"]: index for index, label in enumerate(config["labels"])},
    }


def load_runtime_policy(policy_path=POLICY):
    return json.loads(Path(policy_path).read_text(encoding="utf-8"))


def runtime_policy_sha256(policy_path=POLICY):
    return hashlib.sha256(Path(policy_path).read_bytes()).hexdigest()


def select_runtime_policy(policy, served_at):
    served_time = parse_event_time(served_at)
    selected = dict(policy)
    rules = []
    for rule in policy.get("rules", []):
        if parse_event_time(rule["effective_from"]) > served_time:
            continue
        expires_at = rule.get("expires_at")
        if expires_at is not None and served_time >= parse_event_time(expires_at):
            continue
        rules.append(dict(rule))
    selected["rules"] = rules
    return selected


def load_calibration_events(events_path=CALIBRATION):
    rows = []
    for line in Path(events_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def calibration_events_sha256(events_path=CALIBRATION):
    return hashlib.sha256(Path(events_path).read_bytes()).hexdigest()


def parse_event_time(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def normalize_text(text):
    import unicodedata

    value = unicodedata.normalize("NFKC", str(text)).casefold()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = unicodedata.normalize("NFC", value)
    return " ".join(value.split())


def byte_token(byte_value, tokenizer, position, word_index):
    return {
        "token_id": int(tokenizer["byte_token_offset"]) + byte_value,
        "token": f"<0x{byte_value:02X}>",
        "position": position,
        "word_index": word_index,
        "byte_fallback": True,
    }


def tokenize_text(text, router_or_tokenizer):
    tokenizer = router_or_tokenizer.get("tokenizer", router_or_tokenizer)
    vocab = tokenizer["vocab"]
    rows = []
    for word_index, word in enumerate(normalize_text(text).split()):
        cursor = 0
        at_start = True
        while cursor < len(word):
            best = None
            prefix = "^" if at_start else ""
            for end in range(len(word), cursor, -1):
                candidate = prefix + word[cursor:end]
                if candidate in vocab:
                    best = candidate
                    cursor = end
                    break
            if best is not None:
                rows.append(
                    {
                        "token_id": int(vocab[best]),
                        "token": best,
                        "position": len(rows),
                        "word_index": word_index,
                        "byte_fallback": False,
                    }
                )
                at_start = False
                continue
            ch = word[cursor]
            for byte in ch.encode("utf-8"):
                rows.append(byte_token(byte, tokenizer, len(rows), word_index))
            cursor += 1
            at_start = False
    return rows


def half_even_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    sign = -1 if numerator < 0 else 1
    q, r = divmod(abs(numerator), denominator)
    twice = r * 2
    if twice > denominator or (twice == denominator and q % 2 == 1):
        q += 1
    return sign * q


def calibration_adjustment(event):
    total = sum(int(component["micro"]) for component in event.get("components", []))
    scaled = half_even_div(total * int(event["confidence_ppm"]), 1_000_000)
    limit = abs(int(event["max_abs_adjustment_micro"]))
    return max(-limit, min(limit, scaled))


def compile_calibration_events(events, model_version="router-eval-v1"):
    compiled = []
    for event in events:
        if event.get("model_version") != model_version:
            continue
        row = dict(event)
        row["required_prompt_token_ids"] = [int(token_id) for token_id in event.get("required_prompt_token_ids", [])]
        row["any_prompt_token_ids"] = [int(token_id) for token_id in event.get("any_prompt_token_ids", [])]
        row["blocked_prompt_token_ids"] = [int(token_id) for token_id in event.get("blocked_prompt_token_ids", [])]
        row["target_variant_index"] = int(event["target_variant_index"])
        row["sequence"] = int(event["sequence"])
        row["confidence_ppm"] = int(event["confidence_ppm"])
        row["max_abs_adjustment_micro"] = int(event["max_abs_adjustment_micro"])
        row["adjustment_micro"] = calibration_adjustment(event)
        compiled.append(row)
    compiled.sort(
        key=lambda row: (
            row["calibration_key"],
            parse_event_time(row["event_time"]),
            int(row["sequence"]),
            row["event_id"],
        )
    )
    return {"model_version": model_version, "events": compiled}


def select_calibration_events(calibration, served_at):
    served_time = parse_event_time(served_at)
    current_by_key = {}
    for event in calibration.get("events", []):
        if parse_event_time(event["event_time"]) > served_time:
            continue
        sort_key = (parse_event_time(event["event_time"]), int(event["sequence"]), event["event_id"])
        key = event["calibration_key"]
        if key not in current_by_key or sort_key > current_by_key[key][0]:
            current_by_key[key] = (sort_key, event)
    selected = []
    for key in sorted(current_by_key):
        event = current_by_key[key][1]
        if event.get("status") == "active":
            selected.append(dict(event))
    return {"model_version": calibration.get("model_version", ""), "events": selected}


def base_score(scores, token):
    token_id = int(token["token_id"]) if isinstance(token, dict) else int(token)
    if isinstance(token, dict) and token.get("byte_fallback"):
        return int(scores["byte_base_micro"])
    return int(scores.get("base_micro", {}).get(str(token_id), scores["unknown_base_micro"]))


def transition_score(scores, prev_token_id, token_id):
    return int(scores.get("transition_micro", {}).get(f"{int(prev_token_id)}>{int(token_id)}", 0))


def score_variant(message_tokens, label, variant_index, verbalizer, router):
    label_tokens = tokenize_text(verbalizer, router)
    prev = message_tokens[-1]["token_id"] if message_tokens else router["tokenizer"]["bos_token_id"]
    raw = 0
    token_rows = []
    for index, token in enumerate(label_tokens):
        base = base_score(router["scores"], token)
        transition = transition_score(router["scores"], prev, token["token_id"])
        raw += base + transition
        token_rows.append(
            {
                "token": token["token"],
                "token_id": token["token_id"],
                "position": index,
                "prev_token_id": prev,
                "base_micro": base,
                "transition_micro": transition,
                "running_raw_micro": raw,
                "byte_fallback": token["byte_fallback"],
            }
        )
        prev = token["token_id"]
    normalized = half_even_div(raw, max(1, len(label_tokens)))
    return {
        "label_id": label["label_id"],
        "variant_index": variant_index,
        "verbalizer": verbalizer,
        "raw_micro": raw,
        "token_count": len(label_tokens),
        "normalized_micro": normalized,
        "prior_micro": int(label["prior_micro"]),
        "adjusted_micro": normalized + int(label["prior_micro"]),
        "tokens": token_rows,
    }


def score_candidate(message_tokens, label, router):
    variants = [
        score_variant(message_tokens, label, index, verbalizer, router)
        for index, verbalizer in enumerate(label["verbalizers"])
    ]
    variants.sort(
        key=lambda row: (
            -row["adjusted_micro"],
            -row["normalized_micro"],
            -row["raw_micro"],
            row["variant_index"],
        )
    )
    best = dict(variants[0])
    best["variants"] = variants
    return best


def rule_matches(rule, prompt_token_ids, label_id, variant_index):
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


def event_matches(event, prompt_token_ids, label_id, variant_index):
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


def decorate_variant(variant, prompt_token_ids, policy, calibration):
    matched = [
        rule
        for rule in policy["rules"]
        if rule_matches(rule, prompt_token_ids, variant["label_id"], variant["variant_index"])
    ]
    policy_adjustment = sum(int(rule["adjustment_micro"]) for rule in matched)
    calibration_matches = [
        event
        for event in calibration["events"]
        if event_matches(event, prompt_token_ids, variant["label_id"], variant["variant_index"])
    ]
    calibration_adjustment = sum(int(event["adjustment_micro"]) for event in calibration_matches)
    row = dict(variant)
    row["policy_rule_ids"] = [rule["rule_id"] for rule in matched]
    row["policy_adjustment_micro"] = policy_adjustment
    row["calibration_event_ids"] = [event["event_id"] for event in calibration_matches]
    row["calibration_adjustment_micro"] = calibration_adjustment
    row["runtime_adjusted_micro"] = row["adjusted_micro"] + policy_adjustment + calibration_adjustment
    return row


def apply_runtime_policy(message_tokens, candidate, policy, calibration):
    prompt_token_ids = [token["token_id"] for token in message_tokens]
    variants = [decorate_variant(variant, prompt_token_ids, policy, calibration) for variant in candidate["variants"]]
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


def rank_runtime(scored, router):
    return sorted(
        scored,
        key=lambda row: (
            -row["runtime_adjusted_micro"],
            -row["adjusted_micro"],
            -row["normalized_micro"],
            -row["raw_micro"],
            router["label_order"][row["label_id"]],
        ),
    )


def digest_rows(rows):
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def canonical_digest(value):
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def unique_in_order(values):
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
        policy_ids = unique_in_order(
            rule_id
            for score in prediction["label_scores"]
            for rule_id in score["policy_rule_ids"]
        )
        calibration_ids = unique_in_order(
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
            "policy_snapshot_sha256": canonical_digest(context["policy_rules"]),
            "calibration_snapshot_sha256": canonical_digest(context["calibration_events"]),
            "score_vector_sha256": canonical_digest(prediction["label_scores"]),
            "audit_span_sha256": canonical_digest(audit_by_input.get(input_id, [])),
            "selected_variant_signature": "|".join(
                f"{score['label_id']}:{score['variant_index']}:{score['runtime_adjusted_micro']}"
                for score in prediction["label_scores"]
            ),
        }
        row = dict(partial)
        row["lineage_sha256"] = canonical_digest(partial)
        rows.append(row)
    return rows


def expected_outputs(batch_path):
    router = load_router()
    policy = load_runtime_policy()
    calibration = compile_calibration_events(load_calibration_events(), "router-eval-v1")
    batch_rows = read_jsonl(batch_path)
    latest_served_at = max((row["served_at"] for row in batch_rows), default="1970-01-01T00:00:00Z")
    latest_calibration = select_calibration_events(calibration, latest_served_at)
    config = router["config"]
    predictions = []
    audit_rows = []
    correct = 0
    labeled = 0
    margins = []
    policy_adjustment_count = 0
    calibration_adjustment_count = 0
    trace_contexts = {}

    for item in batch_rows:
        message_tokens = tokenize_text(item["text"], router)
        input_id = item["input_id"]
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
        scored = rank_runtime(
            [
                apply_runtime_policy(message_tokens, score_candidate(message_tokens, label, router), item_policy, item_calibration)
                for label in config["labels"]
            ],
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
        "runtime_policy_sha256": runtime_policy_sha256(),
        "calibration_events_sha256": calibration_events_sha256(),
        "calibration_current_count": len(latest_calibration["events"]),
        "calibration_adjustment_count": calibration_adjustment_count,
        "prediction_count": len(predictions),
        "label_count": len(config["labels"]),
        "abstention_count": sum(1 for row in predictions if row["abstained"]),
        "audit_row_count": len(audit_rows),
        "policy_adjustment_count": policy_adjustment_count,
        "labeled_count": labeled,
        "correct_labeled_count": correct,
        "accuracy_micro": 0 if labeled == 0 else half_even_div(correct * 1_000_000, labeled),
        "mean_margin_micro": half_even_div(sum(margins), max(1, len(margins))),
        "predictions_sha256": digest_rows(predictions),
        "audit_sha256": digest_rows(audit_rows),
        "serving_trace_count": len(serving_trace),
        "serving_trace_sha256": digest_rows(serving_trace),
    }
    return predictions, audit_rows, serving_trace, report


def run_agent_cli(input_path, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "lm-router-score",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        cwd=str(APP),
    )
    return (
        read_jsonl(output_dir / "predictions.jsonl"),
        read_csv(output_dir / "token_score_audit.csv"),
        read_jsonl(output_dir / "serving_trace.jsonl"),
        read_report(output_dir / "evaluation_report.json"),
    )


def test_agent_inputs_are_not_modified():
    """The visible router inputs remain the immutable inputs named in the instruction."""
    for relative_path, expected in EXPECTED_INPUT_SHA256.items():
        assert file_sha256(APP / relative_path) == expected


def test_visible_output_files_exist():
    """The four required /app/output artifacts are present."""
    assert PREDICTIONS_PATH.exists()
    assert AUDIT_PATH.exists()
    assert TRACE_PATH.exists()
    assert REPORT_PATH.exists()


def test_predictions_jsonl_schema_and_sort_order():
    """predictions.jsonl has the required fields, types, and input_id order."""
    rows = read_jsonl(PREDICTIONS_PATH)
    assert [row["input_id"] for row in rows] == sorted(row["input_id"] for row in rows)
    for row in rows:
        assert set(row) == {
            "input_id",
            "predicted_label",
            "top_label",
            "runner_up_label",
            "abstained",
            "margin_micro",
            "label_scores",
        }
        assert isinstance(row["input_id"], str)
        assert isinstance(row["predicted_label"], str)
        assert isinstance(row["abstained"], bool)
        assert isinstance(row["margin_micro"], int)
        assert isinstance(row["label_scores"], list)
        for score in row["label_scores"]:
            assert set(score) == {
                "label_id",
                "variant_index",
                "verbalizer",
                "raw_micro",
                "token_count",
                "normalized_micro",
                "prior_micro",
                "adjusted_micro",
                "policy_rule_ids",
                "policy_adjustment_micro",
                "calibration_event_ids",
                "calibration_adjustment_micro",
                "runtime_adjusted_micro",
            }
            assert isinstance(score["policy_rule_ids"], list)
            assert isinstance(score["policy_adjustment_micro"], int)
            assert isinstance(score["calibration_event_ids"], list)
            assert isinstance(score["calibration_adjustment_micro"], int)
            assert isinstance(score["runtime_adjusted_micro"], int)


def test_visible_predictions_match_reference():
    """Visible-batch label decisions and exact score components match the contract oracle."""
    expected, _, _, _ = expected_outputs(VISIBLE_BATCH)
    assert read_jsonl(PREDICTIONS_PATH) == expected


def test_visible_audit_schema_and_sort_order():
    """token_score_audit.csv has the exact header and stable row order."""
    rows = read_csv(AUDIT_PATH)
    assert rows == sorted(
        rows,
        key=lambda row: (
            row["input_id"],
            row["row_type"],
            row["label_id"],
            int(row["variant_index"] or -1),
            int(row["position"]),
        ),
    )


def test_visible_audit_rows_match_reference():
    """Visible-batch prompt and candidate token audit rows match the contract oracle."""
    _, expected, _, _ = expected_outputs(VISIBLE_BATCH)
    assert read_csv(AUDIT_PATH) == expected


def test_visible_serving_trace_schema_and_sort_order():
    """serving_trace.jsonl has the exact schema, field types, and input_id order."""
    rows = read_jsonl(TRACE_PATH)
    assert [row["input_id"] for row in rows] == sorted(row["input_id"] for row in rows)
    for row in rows:
        assert set(row) == TRACE_FIELDS
        assert isinstance(row["input_id"], str)
        assert isinstance(row["served_at"], str)
        assert isinstance(row["top_label"], str)
        assert isinstance(row["predicted_label"], str)
        assert isinstance(row["abstained"], bool)
        assert isinstance(row["policy_snapshot_rule_count"], int)
        assert isinstance(row["calibration_snapshot_event_count"], int)
        assert isinstance(row["policy_rule_ids"], list)
        assert isinstance(row["calibration_event_ids"], list)
        assert isinstance(row["selected_variant_signature"], str)
        for digest_field in [
            "policy_snapshot_sha256",
            "calibration_snapshot_sha256",
            "score_vector_sha256",
            "audit_span_sha256",
            "lineage_sha256",
        ]:
            assert isinstance(row[digest_field], str)
            assert len(row[digest_field]) == 64


def test_visible_serving_trace_matches_reference():
    """Visible-batch serving lineage rows match the per-request contract oracle."""
    _, _, expected, _ = expected_outputs(VISIBLE_BATCH)
    assert read_jsonl(TRACE_PATH) == expected


def test_visible_report_schema_and_values_match_reference():
    """evaluation_report.json has the required summary fields and exact integer values."""
    _, _, _, expected = expected_outputs(VISIBLE_BATCH)
    actual = read_report()
    assert set(actual) == set(expected)
    assert actual["runtime_policy_id"] == "checkout-intent-runtime-2026-07"
    assert actual["runtime_policy_sha256"] == runtime_policy_sha256()
    assert actual["calibration_events_sha256"] == calibration_events_sha256()
    assert actual == expected


def test_abstain_margin_tie_uses_exact_integer_rule():
    """A margin exactly equal to abstain_margin_micro is an abstention."""
    rows = {row["input_id"]: row for row in read_jsonl(PREDICTIONS_PATH)}
    assert rows["v002"]["margin_micro"] == 25000
    assert rows["v002"]["abstained"] is True
    assert rows["v002"]["predicted_label"] == "ABSTAIN"


def test_prompt_tokens_are_audited_but_not_scored():
    """Prompt tokens appear in the audit with included_in_score=false and blank running totals."""
    prompt_rows = [row for row in read_csv(AUDIT_PATH) if row["row_type"] == "prompt"]
    assert prompt_rows
    assert all(row["included_in_score"] == "false" for row in prompt_rows)
    assert all(row["running_raw_micro"] == "" for row in prompt_rows)
    assert all(row["policy_rule_ids"] == "" for row in prompt_rows)
    assert all(row["calibration_event_ids"] == "" for row in prompt_rows)
    assert all(
        row["policy_adjustment_micro"] == ""
        and row["calibration_adjustment_micro"] == ""
        and row["runtime_adjusted_micro"] == ""
        for row in prompt_rows
    )
    assert all(row["base_micro"] == "0" and row["transition_micro"] == "0" for row in prompt_rows)


def test_all_candidate_labels_are_audited_per_input():
    """Every input has continuation rows for every configured label variant, not only the winner."""
    config = load_router()["config"]
    expected_pairs = {
        (label["label_id"], str(index))
        for label in config["labels"]
        for index, _ in enumerate(label["verbalizers"])
    }
    rows = read_csv(AUDIT_PATH)
    for input_id in {row["input_id"] for row in rows}:
        audited = {
            (row["label_id"], row["variant_index"])
            for row in rows
            if row["input_id"] == input_id and row["row_type"] == "candidate"
        }
        assert audited == expected_pairs


def test_unicode_normalization_drives_visible_cafe_case():
    """The decomposed cafe input is normalized before tokenization and routes as refund_status."""
    predictions = {row["input_id"]: row for row in read_jsonl(PREDICTIONS_PATH)}
    assert predictions["v005"]["predicted_label"] == "refund_status"
    prompt_tokens = [row["token"] for row in read_csv(AUDIT_PATH) if row["input_id"] == "v005" and row["row_type"] == "prompt"]
    assert "^cafe" in prompt_tokens


def test_byte_fallback_trace_is_present_for_visible_emoji():
    """The emoji in v007 is represented as UTF-8 byte fallback tokens in the prompt audit."""
    rows = [row for row in read_csv(AUDIT_PATH) if row["input_id"] == "v007" and row["row_type"] == "prompt"]
    assert [row["token"] for row in rows[-4:]] == ["<0xF0>", "<0x9F>", "<0x98>", "<0x95>"]
    assert rows[-1]["token_id"] == "1149"


def test_length_normalization_uses_candidate_tokens_only():
    """The shipping_delay score divides by its three continuation tokens, not by prompt length."""
    row = next(
        score
        for pred in read_jsonl(PREDICTIONS_PATH)
        if pred["input_id"] == "v001"
        for score in pred["label_scores"]
        if score["label_id"] == "shipping_delay"
    )
    assert row["token_count"] == 3
    assert row["normalized_micro"] == half_even_div(row["raw_micro"], 3)


def test_report_digests_are_recomputed_from_parsed_outputs():
    """Report digests match canonical hashes of the parsed output rows."""
    report = read_report()
    assert report["predictions_sha256"] == digest_rows(read_jsonl(PREDICTIONS_PATH))
    assert report["audit_sha256"] == digest_rows(read_csv(AUDIT_PATH))
    assert report["serving_trace_sha256"] == digest_rows(read_jsonl(TRACE_PATH))
    assert report["serving_trace_count"] == len(read_jsonl(TRACE_PATH))


def test_report_closeout_keeps_calibration_and_parsed_digest_semantics():
    """The final report keeps compiled calibration counts and parsed-row digests after artifact closeout."""
    report = read_report()
    assert report["calibration_current_count"] == 6
    assert report["calibration_adjustment_count"] == 1
    assert report["audit_sha256"] != hashlib.sha256(AUDIT_PATH.read_bytes()).hexdigest()
    assert report["serving_trace_sha256"] != hashlib.sha256(TRACE_PATH.read_bytes()).hexdigest()


def test_public_helper_api_can_be_imported():
    """The repaired package exposes the documented helper functions."""
    module = importlib.import_module("lm_router.scorer")
    runtime = importlib.import_module("lm_router.runtime")
    calibration = importlib.import_module("lm_router.calibration")
    for name in ["load_router", "normalize_text", "tokenize_text", "score_candidate"]:
        assert callable(getattr(module, name))
    for name in [
        "load_runtime_policy",
        "select_runtime_policy",
        "apply_runtime_policy",
        "build_serving_trace",
        "score_runtime_batch",
        "write_runtime_outputs",
    ]:
        assert callable(getattr(runtime, name))
    for name in ["load_calibration_events", "compile_calibration_events", "select_calibration_events", "calibration_events_sha256"]:
        assert callable(getattr(calibration, name))


def test_public_normalize_text_matches_contract():
    """normalize_text applies NFKC, casefolding, accent removal, and whitespace collapse."""
    from lm_router.scorer import normalize_text as agent_normalize

    assert agent_normalize("  Cafe\u0301   \uff30\uff32\uff2f\uff2d\uff2f  ") == "cafe promo"


def test_public_tokenize_text_splits_word_initial_and_continuation_pieces():
    """tokenize_text greedily emits ^ship then ping for the word shipping."""
    from lm_router.scorer import load_router as agent_load_router
    from lm_router.scorer import tokenize_text as agent_tokenize

    router = agent_load_router(str(CONFIG), str(TOKENIZER), str(SCORES))
    rows = agent_tokenize("shipping", router)
    assert [(row["token"], row["token_id"]) for row in rows] == [("^ship", 103), ("ping", 104)]


def test_public_tokenize_text_uses_byte_fallback_shape():
    """tokenize_text emits one documented byte-fallback row per UTF-8 byte for unknown characters."""
    from lm_router.scorer import load_router as agent_load_router
    from lm_router.scorer import tokenize_text as agent_tokenize

    router = agent_load_router(str(CONFIG), str(TOKENIZER), str(SCORES))
    rows = agent_tokenize("\U0001f615", router)
    assert [row["token"] for row in rows] == ["<0xF0>", "<0x9F>", "<0x98>", "<0x95>"]
    assert [row["token_id"] for row in rows] == [1240, 1159, 1152, 1149]
    assert all(row["byte_fallback"] is True for row in rows)


def test_public_score_candidate_uses_prompt_context_transition():
    """score_candidate uses the last prompt token as the first continuation context."""
    from lm_router.scorer import load_router as agent_load_router
    from lm_router.scorer import score_candidate as agent_score_candidate
    from lm_router.scorer import tokenize_text as agent_tokenize

    router = agent_load_router(str(CONFIG), str(TOKENIZER), str(SCORES))
    label = next(label for label in router["config"]["labels"] if label["label_id"] == "billing_issue")
    scored = agent_score_candidate(agent_tokenize("charged twice", router), label, router)
    assert scored["tokens"][0]["prev_token_id"] == 124
    assert scored["tokens"][0]["transition_micro"] == 980000
    assert set(scored) == {
        "label_id",
        "variant_index",
        "verbalizer",
        "raw_micro",
        "token_count",
        "normalized_micro",
        "prior_micro",
        "adjusted_micro",
        "tokens",
        "variants",
    }
    for variant in scored["variants"]:
        for token in variant["tokens"]:
            assert {
                "token",
                "token_id",
                "position",
                "prev_token_id",
                "base_micro",
                "transition_micro",
                "running_raw_micro",
                "byte_fallback",
            } <= set(token)


def test_public_runtime_batch_return_shapes_are_documented():
    """score_runtime_batch returns predictions, audit rows, serving trace, and report objects."""
    from lm_router.scorer import load_router as agent_load_router
    from lm_router.calibration import compile_calibration_events as agent_compile_calibration
    from lm_router.calibration import load_calibration_events as agent_load_calibration
    from lm_router.runtime import load_runtime_policy as agent_load_policy
    from lm_router.runtime import score_runtime_batch as agent_score_runtime_batch

    router = agent_load_router(str(CONFIG), str(TOKENIZER), str(SCORES))
    policy = agent_load_policy(str(POLICY))
    calibration = agent_compile_calibration(agent_load_calibration(str(CALIBRATION)), "router-eval-v1")
    predictions, audit_rows, serving_trace, report = agent_score_runtime_batch(
        str(VISIBLE_BATCH),
        router,
        policy,
        str(POLICY),
        calibration,
        str(CALIBRATION),
    )
    assert isinstance(predictions, list)
    assert isinstance(audit_rows, list)
    assert isinstance(serving_trace, list)
    assert isinstance(report, dict)
    assert report["prediction_count"] == len(predictions)
    assert report["audit_row_count"] == len(audit_rows)
    assert report["serving_trace_count"] == len(serving_trace)
    assert report["serving_trace_sha256"] == digest_rows(serving_trace)
    assert report["runtime_policy_sha256"] == runtime_policy_sha256()
    assert report["calibration_events_sha256"] == calibration_events_sha256()
    assert report["calibration_current_count"] == 6


def test_public_runtime_policy_selector_uses_served_at_window():
    """Runtime policy helper selects rules by the served_at effective window."""
    from lm_router.runtime import load_runtime_policy as agent_load_policy
    from lm_router.runtime import select_runtime_policy as agent_select_policy

    policy = agent_load_policy(str(POLICY))
    early = [rule["rule_id"] for rule in agent_select_policy(policy, "2026-07-01T10:00:00Z")["rules"]]
    current = [rule["rule_id"] for rule in agent_select_policy(policy, "2026-07-05T10:00:00Z")["rules"]]
    assert "invoice-repeat-prefers-invoice-charge" not in early
    assert "damaged-label-prefers-return-label" in early
    assert "invoice-repeat-prefers-invoice-charge" in current
    assert len(current) == 6


def test_public_calibration_compiler_uses_timeline_and_request_snapshot():
    """Calibration helpers expose the full timeline and select request-time current rows."""
    from lm_router.calibration import compile_calibration_events as agent_compile_calibration
    from lm_router.calibration import load_calibration_events as agent_load_calibration
    from lm_router.calibration import select_calibration_events as agent_select_calibration

    compiled = agent_compile_calibration(agent_load_calibration(str(CALIBRATION)), "router-eval-v1")
    assert len(compiled["events"]) == 10
    assert all("calibration_key" in event and "status" in event for event in compiled["events"])
    before_void = {event["calibration_key"]: event for event in agent_select_calibration(compiled, "2026-07-02T11:00:00Z")["events"]}
    after_void = {event["calibration_key"]: event for event in agent_select_calibration(compiled, "2026-07-05T12:00:00Z")["events"]}
    assert set(after_void) == {
        "account_access_without_password",
        "emoji_general_help",
        "invoice_repeat_label",
        "lost_package_label",
        "pickup_store_label",
        "refund_damaged_label",
    }
    assert before_void["gift_card_label"]["event_id"] == "cal-gift-old"
    assert before_void["gift_card_label"]["adjustment_micro"] == 50000
    assert "gift_card_label" not in after_void
    assert after_void["refund_damaged_label"]["event_id"] == "cal-refund-current"
    assert after_void["pickup_store_label"]["event_id"] == "cal-pickup-current"
    assert after_void["invoice_repeat_label"]["adjustment_micro"] == 116000
    assert after_void["lost_package_label"]["adjustment_micro"] == 91000
    assert after_void["account_access_without_password"]["adjustment_micro"] == 70000
    assert after_void["emoji_general_help"]["adjustment_micro"] == -30000


def test_hidden_cli_predictions_match_reference(tmp_path):
    """The reusable CLI produces exact hidden-batch predictions, not just visible outputs."""
    actual, _, _, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    expected, _, _, _ = expected_outputs(HIDDEN_BATCH)
    assert actual == expected


def test_hidden_cli_audit_matches_reference(tmp_path):
    """The reusable CLI produces exact hidden-batch token audit rows."""
    _, actual, _, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    _, expected, _, _ = expected_outputs(HIDDEN_BATCH)
    assert actual == expected


def test_hidden_cli_serving_trace_matches_reference(tmp_path):
    """The reusable CLI produces exact hidden-batch serving lineage rows."""
    _, _, actual, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    _, _, expected, _ = expected_outputs(HIDDEN_BATCH)
    assert actual == expected


def test_hidden_cli_report_matches_reference(tmp_path):
    """The reusable CLI produces exact hidden-batch evaluation report values and digests."""
    _, _, _, actual = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    _, _, _, expected = expected_outputs(HIDDEN_BATCH)
    assert actual == expected


def test_hidden_fullwidth_and_byte_fallback_compose(tmp_path):
    """A hidden row combines NFKC text and byte fallback before scoring general_help."""
    actual, audit, _, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    row = next(row for row in actual if row["input_id"] == "h006")
    assert row["predicted_label"] == "general_help"
    prompt_tokens = [row["token"] for row in audit if row["input_id"] == "h006" and row["row_type"] == "prompt"]
    assert "^promo" in prompt_tokens
    assert prompt_tokens[-4:] == ["<0xF0>", "<0x9F>", "<0x98>", "<0x95>"]


def test_hidden_empty_text_uses_bos_context(tmp_path):
    """A hidden empty string uses bos_token_id as the first continuation context."""
    _, audit, _, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    rows = [row for row in audit if row["input_id"] == "h007" and row["label_id"] == "billing_issue"]
    assert rows[0]["prev_token_id"] == "2"


def test_hidden_trace_level_correctness_not_only_final_labels(tmp_path):
    """Hidden examples require exact trace fields even when the final label is plausible."""
    actual, audit, trace, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    assert next(row for row in actual if row["input_id"] == "h003")["predicted_label"] == "general_help"
    general_rows = [row for row in audit if row["input_id"] == "h003" and row["label_id"] == "general_help"]
    assert general_rows[0]["prev_token_id"] == "129"
    assert general_rows[0]["transition_micro"] == "650000"
    trace_row = next(row for row in trace if row["input_id"] == "h003")
    assert trace_row["calibration_event_ids"] == ["cal-gift-old"]
    assert trace_row["calibration_snapshot_event_count"] == 3
    assert trace_row["lineage_sha256"] == canonical_digest(
        {key: value for key, value in trace_row.items() if key != "lineage_sha256"}
    )


def test_hidden_late_delivery_uses_context_not_label_base_only(tmp_path):
    """A hidden delivery message routes by prompt-to-label transition, not static label priors."""
    actual, _, _, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    row = next(row for row in actual if row["input_id"] == "h001")
    assert row["predicted_label"] == "shipping_delay"
    assert row["top_label"] == "shipping_delay"


def test_hidden_report_accuracy_ignores_unlabeled_empty_row(tmp_path):
    """The hidden report accuracy denominator uses only rows with a non-empty gold_label."""
    _, _, _, report = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    assert report["prediction_count"] == 14
    assert report["labeled_count"] == 13
    assert report["correct_labeled_count"] == 13
    assert report["accuracy_micro"] == 1000000


def test_hidden_non_primary_verbalizers_drive_selected_variants(tmp_path):
    """Hidden rows require scoring non-primary verbalizer variants, not only the first phrase per label."""
    actual, audit, _, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    rows = {row["input_id"]: row for row in actual}
    assert rows["h008"]["top_label"] == "billing_issue"
    assert next(score for score in rows["h008"]["label_scores"] if score["label_id"] == "billing_issue")[
        "variant_index"
    ] == 1
    assert rows["h009"]["top_label"] == "shipping_delay"
    assert next(score for score in rows["h009"]["label_scores"] if score["label_id"] == "shipping_delay")[
        "variant_index"
    ] == 2
    assert rows["h010"]["top_label"] == "refund_status"
    assert next(score for score in rows["h010"]["label_scores"] if score["label_id"] == "refund_status")[
        "variant_index"
    ] == 1
    assert rows["h011"]["top_label"] == "account_access"
    assert next(score for score in rows["h011"]["label_scores"] if score["label_id"] == "account_access")[
        "variant_index"
    ] == 1
    audited_pairs = {
        (row["input_id"], row["label_id"], row["variant_index"])
        for row in audit
        if row["row_type"] == "candidate"
    }
    assert ("h008", "billing_issue", "1") in audited_pairs
    assert ("h009", "shipping_delay", "2") in audited_pairs
    assert ("h010", "refund_status", "1") in audited_pairs
    assert ("h011", "account_access", "1") in audited_pairs


def test_hidden_runtime_policy_adjustments_are_applied_to_all_variants(tmp_path):
    """Hidden rows require the serving policy and compiled calibration events."""
    actual, audit, _, report = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    rows = {row["input_id"]: row for row in actual}
    expected_overlays = {
        ("h003", "general_help"): ("", "cal-gift-old", 50000),
        ("h004", "refund_status"): ("damaged-label-prefers-return-label", "cal-refund-current", 340000),
        ("h005", "general_help"): ("pickup-store-prefers-store-pickup", "cal-pickup-current", 320000),
        ("h006", "general_help"): ("emoji-general-help-dampen", "cal-emoji-current", -30000),
        ("h008", "billing_issue"): ("invoice-repeat-prefers-invoice-charge", "cal-invoice-current", 116000),
        ("h009", "shipping_delay"): ("lost-package-prefers-package-lost", "cal-lost-current", 91000),
        ("h011", "account_access"): ("account-access-without-password", "cal-account-current", 70000),
        ("h014", "refund_status"): ("damaged-label-prefers-return-label", "cal-refund-old", 120000),
    }
    for (input_id, label_id), (rule_id, event_id, event_adjustment) in expected_overlays.items():
        score = next(score for score in rows[input_id]["label_scores"] if score["label_id"] == label_id)
        expected_rule_ids = [] if rule_id == "" else [rule_id]
        assert score["policy_rule_ids"] == expected_rule_ids
        assert score["calibration_event_ids"] == [event_id]
        if expected_rule_ids:
            assert score["policy_adjustment_micro"] != 0
        else:
            assert score["policy_adjustment_micro"] == 0
        assert score["calibration_adjustment_micro"] == event_adjustment
        assert score["runtime_adjusted_micro"] == (
            score["adjusted_micro"] + score["policy_adjustment_micro"] + score["calibration_adjustment_micro"]
        )
        candidate_rows = [
            row
            for row in audit
            if row["input_id"] == input_id and row["label_id"] == label_id and row["variant_index"] == str(score["variant_index"])
        ]
        assert candidate_rows
        assert {row["policy_rule_ids"] for row in candidate_rows} == {rule_id}
        assert {row["calibration_event_ids"] for row in candidate_rows} == {event_id}
        assert {row["calibration_adjustment_micro"] for row in candidate_rows} == {str(event_adjustment)}
    expected_policy_count = sum(1 for rule_id, _, _ in expected_overlays.values() if rule_id)
    assert report["policy_adjustment_count"] >= expected_policy_count
    assert report["calibration_current_count"] == 6
    assert report["calibration_adjustment_count"] == len(expected_overlays)


def test_hidden_void_and_blocked_calibration_events_do_not_apply(tmp_path):
    """Voided current calibration and blocked prompt tokens are excluded from runtime overlays."""
    actual, _, trace, _ = run_agent_cli(HIDDEN_BATCH, tmp_path / "hidden")
    rows = {row["input_id"]: row for row in actual}
    gift = next(score for score in rows["h012"]["label_scores"] if score["label_id"] == "general_help")
    assert gift["calibration_event_ids"] == []
    assert gift["calibration_adjustment_micro"] == 0
    password = next(score for score in rows["h002"]["label_scores"] if score["label_id"] == "account_access")
    assert password["calibration_event_ids"] == []
    assert password["calibration_adjustment_micro"] == 0
    early_invoice = next(score for score in rows["h013"]["label_scores"] if score["label_id"] == "billing_issue")
    assert early_invoice["policy_rule_ids"] == []
    assert early_invoice["calibration_event_ids"] == []
    assert early_invoice["calibration_adjustment_micro"] == 0
    trace_rows = {row["input_id"]: row for row in trace}
    assert trace_rows["h012"]["calibration_event_ids"] == []
    assert trace_rows["h013"]["policy_rule_ids"] == []
    assert trace_rows["h013"]["calibration_event_ids"] == []
    assert trace_rows["h013"]["policy_snapshot_rule_count"] < trace_rows["h008"]["policy_snapshot_rule_count"]
    assert trace_rows["h013"]["calibration_snapshot_event_count"] < trace_rows["h008"]["calibration_snapshot_event_count"]


def test_no_extra_output_files_are_required():
    """The required output contract includes the four named artifacts."""
    produced = {path.name for path in OUTPUT.iterdir() if path.is_file()}
    assert {"predictions.jsonl", "token_score_audit.csv", "serving_trace.jsonl", "evaluation_report.json"} <= produced


def test_prediction_labels_are_known_or_abstain():
    """Every predicted label is either a configured label_id or the configured abstain label."""
    config = load_router()["config"]
    allowed = {label["label_id"] for label in config["labels"]} | {config["abstain_label"]}
    assert {row["predicted_label"] for row in read_jsonl(PREDICTIONS_PATH)} <= allowed


def test_candidate_running_raw_micro_is_cumulative():
    """Candidate audit running_raw_micro equals cumulative base plus transition values."""
    by_variant = {}
    for row in read_csv(AUDIT_PATH):
        if row["input_id"] == "v001" and row["label_id"] == "shipping_delay":
            by_variant.setdefault(row["variant_index"], []).append(row)
    assert set(by_variant) == {"0", "1", "2"}
    for rows in by_variant.values():
        total = 0
        for row in rows:
            total += int(row["base_micro"]) + int(row["transition_micro"])
            assert int(row["running_raw_micro"]) == total
