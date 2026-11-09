from __future__ import annotations

import json
from pathlib import Path

from sim_workspace import (
    DATA_DIR,
    OUTPUT_DIR,
    POLICY_PATH,
    REFERENCE_DIGESTS_PATH,
    REGISTRY_PATH,
    SCENARIO_PATH,
    STEP_MANIFEST_PATH,
    WORK_DIR,
)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)

    scenario = {
        "scenario_id": "STACK-12B",
        "frame_count": 128,
        "thread_buckets": 4,
        "body_count": 6,
        "seed": 4242,
    }
    SCENARIO_PATH.write_text(json.dumps(scenario, indent=2) + "\n", encoding="utf-8")

    steps = [
        "contact_gather",
        "impulse_reduce",
        "integrate",
        "frame_digest",
        "twin_compare",
        "report_emit",
        "finalize",
    ]
    STEP_MANIFEST_PATH.write_text("\n".join(steps) + "\n", encoding="utf-8")

    REGISTRY_PATH.write_text(
        json.dumps(
            {
                "step_verbs": {
                    "contact_gather": "gather_contacts",
                    "impulse_reduce": "reduce_impulses",
                    "integrate": "euler_step",
                    "frame_digest": "hash_frame",
                    "twin_compare": "compare_runs",
                    "report_emit": "emit_reports",
                    "finalize": "seal_run",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    POLICY_PATH.write_text(
        json.dumps(
            {
                "step_verbs": {
                    "contact_gather": "skip_contacts",
                    "impulse_reduce": "serial_only",
                    "integrate": "freeze_vel",
                    "frame_digest": "first_last_only",
                    "twin_compare": "assume_match",
                    "report_emit": "touched",
                    "finalize": "touched",
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    seed_ref = Path(__file__).resolve().parent / "reference_frame_digests_seed.json"
    REFERENCE_DIGESTS_PATH.write_text(seed_ref.read_text(encoding="utf-8"), encoding="utf-8")


if __name__ == "__main__":
    main()
