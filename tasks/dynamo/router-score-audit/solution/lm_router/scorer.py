import csv
import hashlib
import json
import unicodedata
from pathlib import Path


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
]


def load_router(
    config_path="/app/data/router_config.json",
    tokenizer_path="/app/model/tokenizer.json",
    scores_path="/app/model/token_scores.json",
):
    config = json.loads(Path(config_path).read_text())
    tokenizer = json.loads(Path(tokenizer_path).read_text())
    scores = json.loads(Path(scores_path).read_text())
    order = {label["label_id"]: index for index, label in enumerate(config["labels"])}
    for label in config["labels"]:
        if "verbalizers" not in label:
            label["verbalizers"] = [label["verbalizer"]]
    return {"config": config, "tokenizer": tokenizer, "scores": scores, "label_order": order}


def normalize_text(text):
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = unicodedata.normalize("NFC", value)
    return " ".join(value.split())


def _byte_token(byte_value, tokenizer, position, word_index):
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
    words = normalize_text(text).split()
    rows = []
    for word_index, word in enumerate(words):
        cursor = 0
        at_start = True
        while cursor < len(word):
            best = None
            prefix = "^" if at_start else ""
            for end in range(len(word), cursor, -1):
                piece_text = word[cursor:end]
                candidate = prefix + piece_text
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
                rows.append(_byte_token(byte, tokenizer, len(rows), word_index))
            cursor += 1
            at_start = False
    return rows


def _base_score(scores, token):
    token_id = int(token["token_id"]) if isinstance(token, dict) else int(token)
    if isinstance(token, dict) and token.get("byte_fallback"):
        return int(scores["byte_base_micro"])
    return int(scores.get("base_micro", {}).get(str(token_id), scores["unknown_base_micro"]))


def _transition_score(scores, prev_token_id, token_id):
    return int(scores.get("transition_micro", {}).get(f"{int(prev_token_id)}>{int(token_id)}", 0))


def _half_even_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    sign = -1 if numerator < 0 else 1
    q, r = divmod(abs(numerator), denominator)
    twice = r * 2
    if twice > denominator or (twice == denominator and q % 2 == 1):
        q += 1
    return sign * q


def _score_variant(message_tokens, label, variant_index, verbalizer, router):
    scores = router["scores"]
    tokenizer = router["tokenizer"]
    label_tokens = tokenize_text(verbalizer, router)
    prev = message_tokens[-1]["token_id"] if message_tokens else tokenizer["bos_token_id"]
    raw = 0
    token_rows = []
    for index, token in enumerate(label_tokens):
        base = _base_score(scores, token)
        transition = _transition_score(scores, prev, token["token_id"])
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
    normalized = _half_even_div(raw, max(1, len(label_tokens)))
    prior = int(label["prior_micro"])
    return {
        "label_id": label["label_id"],
        "variant_index": variant_index,
        "verbalizer": verbalizer,
        "raw_micro": raw,
        "token_count": len(label_tokens),
        "normalized_micro": normalized,
        "prior_micro": prior,
        "adjusted_micro": normalized + prior,
        "tokens": token_rows,
    }


def score_candidate(message_tokens, label, router):
    variants = [
        _score_variant(message_tokens, label, index, verbalizer, router)
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


def _read_jsonl(path):
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _rank(scored, router):
    order = router["label_order"]
    return sorted(
        scored,
        key=lambda row: (
            -row["adjusted_micro"],
            -row["normalized_micro"],
            -row["raw_micro"],
            order[row["label_id"]],
        ),
    )


def _digest_rows(rows):
    blob = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
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

        scored = _rank([score_candidate(message_tokens, label, router) for label in config["labels"]], router)
        top, runner_up = scored[0], scored[1]
        margin = top["adjusted_micro"] - runner_up["adjusted_micro"]
        abstained = margin <= int(config["abstain_margin_micro"])
        predicted = config["abstain_label"] if abstained else top["label_id"]

        for candidate in scored:
            for variant in candidate["variants"]:
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
    report = {
        "schema_version": "router-eval-v1",
        "prediction_count": len(predictions),
        "label_count": len(config["labels"]),
        "abstention_count": sum(1 for row in predictions if row["abstained"]),
        "audit_row_count": len(audit_rows),
        "labeled_count": labeled,
        "correct_labeled_count": correct,
        "accuracy_micro": 0 if labeled == 0 else _half_even_div(correct * 1_000_000, labeled),
        "mean_margin_micro": _half_even_div(sum(margins), max(1, len(margins))),
        "predictions_sha256": _digest_rows(predictions),
        "audit_sha256": _digest_rows(audit_rows),
    }
    return predictions, audit_rows, report


def write_outputs(predictions, audit_rows, report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / "predictions.jsonl").open("w", encoding="utf-8") as handle:
        for row in predictions:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    with (output_dir / "token_score_audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=AUDIT_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(audit_rows)
    (output_dir / "evaluation_report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
