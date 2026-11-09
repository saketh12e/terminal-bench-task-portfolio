import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def load_calibration_events(events_path="/app/model/calibration_events.jsonl"):
    rows = []
    for line in Path(events_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def calibration_events_sha256(events_path="/app/model/calibration_events.jsonl"):
    return hashlib.sha256(Path(events_path).read_bytes()).hexdigest()


def _parse_time(value):
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _half_even_div(numerator, denominator):
    numerator = int(numerator)
    denominator = int(denominator)
    sign = -1 if numerator < 0 else 1
    q, r = divmod(abs(numerator), denominator)
    twice = r * 2
    if twice > denominator or (twice == denominator and q % 2 == 1):
        q += 1
    return sign * q


def _event_adjustment(event):
    total = sum(int(component["micro"]) for component in event.get("components", []))
    scaled = _half_even_div(total * int(event["confidence_ppm"]), 1_000_000)
    limit = abs(int(event["max_abs_adjustment_micro"]))
    return max(-limit, min(limit, scaled))


def compile_calibration_events(events, model_version):
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
        row["adjustment_micro"] = _event_adjustment(event)
        compiled.append(row)

    compiled.sort(
        key=lambda row: (
            row["calibration_key"],
            _parse_time(row["event_time"]),
            int(row["sequence"]),
            row["event_id"],
        )
    )
    return {"model_version": model_version, "events": compiled}


def select_calibration_events(calibration, served_at):
    served_time = _parse_time(served_at)
    current_by_key = {}
    for event in calibration.get("events", []):
        if _parse_time(event["event_time"]) > served_time:
            continue
        sort_key = (_parse_time(event["event_time"]), int(event["sequence"]), event["event_id"])
        key = event["calibration_key"]
        if key not in current_by_key or sort_key > current_by_key[key][0]:
            current_by_key[key] = (sort_key, event)

    selected = []
    for key in sorted(current_by_key):
        event = current_by_key[key][1]
        if event.get("status") == "active":
            selected.append(dict(event))
    return {"model_version": calibration.get("model_version", ""), "events": selected}
