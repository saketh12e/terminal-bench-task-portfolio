import json
from pathlib import Path


def load_calibration_events(events_path="/app/model/calibration_events.jsonl"):
    rows = []
    for line in Path(events_path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def calibration_events_sha256(events_path="/app/model/calibration_events.jsonl"):
    # Broken behavior: this is not the digest of the exact calibration file.
    return ""


def compile_calibration_events(events, model_version):
    # Broken behavior: accepts the first active row for each key and ignores
    # event-time ordering, confidence scaling, clamp limits, and voided current
    # records. The serving runtime also fails to use the compiled events.
    compiled = []
    seen = set()
    for event in events:
        key = event["calibration_key"]
        if key in seen or event.get("model_version") != model_version:
            continue
        if event.get("status") != "active":
            continue
        seen.add(key)
        row = dict(event)
        row["adjustment_micro"] = sum(int(part["micro"]) for part in event.get("components", []))
        compiled.append(row)
    return {"model_version": model_version, "events": compiled}


def select_calibration_events(calibration, served_at):
    # Broken behavior: ignores the request timestamp and returns the already
    # collapsed global bundle.
    return calibration
