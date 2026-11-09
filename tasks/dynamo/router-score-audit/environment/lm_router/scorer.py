import csv
import hashlib
import json
from pathlib import Path


def load_router(
    config_path="/app/data/router_config.json",
    tokenizer_path="/app/model/tokenizer.json",
    scores_path="/app/model/token_scores.json",
):
    config = json.loads(Path(config_path).read_text())
    tokenizer = json.loads(Path(tokenizer_path).read_text())
    scores = json.loads(Path(scores_path).read_text())
    for label in config["labels"]:
        if "verbalizer" not in label:
            label["verbalizer"] = label["verbalizers"][0]
    return {"config": config, "tokenizer": tokenizer, "scores": scores}


def normalize_text(text):
    return " ".join(str(text).strip().lower().split())


def tokenize_text(text, router_or_tokenizer):
    tokenizer = router_or_tokenizer.get("tokenizer", router_or_tokenizer)
    vocab = tokenizer["vocab"]
    unknown_id = tokenizer["unknown_token_id"]
    pieces = []
    for word_index, word in enumerate(normalize_text(text).split()):
        token = "^" + word
        token_id = vocab.get(token, unknown_id)
        pieces.append(
            {
                "token_id": token_id,
                "token": token if token in vocab else "<unk>",
                "position": len(pieces),
                "word_index": word_index,
                "byte_fallback": False,
            }
        )
    return pieces


def _base_score(scores, token_id):
    return int(scores.get("base_micro", {}).get(str(token_id), scores["unknown_base_micro"]))


def _transition_score(scores, prev_token_id, token_id):
    return int(scores.get("transition_micro", {}).get(f"{prev_token_id}>{token_id}", 0))


def _half_even_div(numerator, denominator):
    q, r = divmod(abs(int(numerator)), int(denominator))
    doubled = r * 2
    if doubled > denominator or (doubled == denominator and q % 2 == 1):
        q += 1
    return q if numerator >= 0 else -q


def score_candidate(message_tokens, label, router):
    scores = router["scores"]
    label_tokens = tokenize_text(label["verbalizer"], router)
    # Broken behavior: prompt tokens leak into the score, and continuation
    # transitions are ignored after the first token.
    raw_micro = sum(_base_score(scores, row["token_id"]) for row in message_tokens)
    prev_id = message_tokens[-1]["token_id"] if message_tokens else router["tokenizer"]["bos_token_id"]
    rows = []
    for index, row in enumerate(label_tokens):
        base = _base_score(scores, row["token_id"])
        transition = _transition_score(scores, prev_id, row["token_id"]) if index == 0 else 0
        raw_micro += base + transition
        rows.append(
            {
                "token": row["token"],
                "token_id": row["token_id"],
                "position": index,
                "base_micro": base,
                "transition_micro": transition,
                "running_raw_micro": raw_micro,
            }
        )
    normalized = _half_even_div(raw_micro, max(1, len(message_tokens) + len(label_tokens)))
    return {
        "label_id": label["label_id"],
        "raw_micro": raw_micro,
        "token_count": len(label_tokens),
        "normalized_micro": normalized,
        "prior_micro": int(label["prior_micro"]),
        "adjusted_micro": normalized + int(label["prior_micro"]),
        "tokens": rows,
    }


def _read_jsonl(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _digest_rows(rows):
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(blob).hexdigest()


def score_batch(batch_path, router):
    config = router["config"]
    predictions = []
    audit_rows = []
    correct = 0
    labeled = 0
    margins = []

    for item in _read_jsonl(batch_path):
        input_id = item["input_id"]
        message_tokens = tokenize_text(item["text"], router)
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
                }
            )

        scored = [score_candidate(message_tokens, label, router) for label in config["labels"]]
        scored.sort(key=lambda s: (-s["adjusted_micro"], -s["normalized_micro"], -s["raw_micro"], s["label_id"]))
        top = scored[0]
        runner_up = scored[1]
        margin = top["adjusted_micro"] - runner_up["adjusted_micro"]
        abstained = margin < int(config["abstain_margin_micro"])
        predicted = config["abstain_label"] if abstained else top["label_id"]

        for candidate in scored:
            prev = message_tokens[-1]["token_id"] if message_tokens else router["tokenizer"]["bos_token_id"]
            for token in candidate["tokens"]:
                audit_rows.append(
                    {
                        "input_id": input_id,
                        "label_id": candidate["label_id"],
                        "variant_index": "0",
                        "row_type": "candidate",
                        "position": str(token["position"]),
                        "token_id": str(token["token_id"]),
                        "token": token["token"],
                        "prev_token_id": str(prev),
                        "base_micro": str(token["base_micro"]),
                        "transition_micro": str(token["transition_micro"]),
                        "included_in_score": "true",
                        "running_raw_micro": str(token["running_raw_micro"]),
                    }
                )
                prev = token["token_id"]

        score_rows = [
            {
                "label_id": row["label_id"],
                "variant_index": 0,
                "verbalizer": next(label["verbalizer"] for label in config["labels"] if label["label_id"] == row["label_id"]),
                "raw_micro": row["raw_micro"],
                "token_count": row["token_count"],
                "normalized_micro": row["normalized_micro"],
                "prior_micro": row["prior_micro"],
                "adjusted_micro": row["adjusted_micro"],
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
                "label_scores": score_rows,
            }
        )
        if item.get("gold_label"):
            labeled += 1
            if predicted == item["gold_label"]:
                correct += 1
        margins.append(margin)

    predictions.sort(key=lambda row: row["input_id"])
    audit_rows.sort(key=lambda row: (row["input_id"], row["row_type"], row["label_id"], int(row["position"])))
    report = {
        "schema_version": "router-eval-v1",
        "prediction_count": len(predictions),
        "label_count": len(config["labels"]),
        "abstention_count": sum(1 for row in predictions if row["abstained"]),
        "audit_row_count": len(audit_rows),
        "labeled_count": labeled,
        "correct_labeled_count": correct,
        "accuracy_micro": _half_even_div(correct * 1_000_000, max(1, labeled)),
        "mean_margin_micro": _half_even_div(sum(margins), max(1, len(margins))),
        "predictions_sha256": _digest_rows(predictions),
        "audit_sha256": _digest_rows(audit_rows),
    }
    return predictions, audit_rows, report


def write_outputs(predictions, audit_rows, report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "predictions.jsonl").open("w") as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    fields = [
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
    ]
    with (output_dir / "token_score_audit.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(audit_rows)
    (output_dir / "evaluation_report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n"
    )
