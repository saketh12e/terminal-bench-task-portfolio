"""Synthesize a disclosure-conditioned rollout and bounded evidence artifacts."""

import argparse
import json
from pathlib import Path
import numpy as np
from lottery import RolloutGame
from certificate import outputs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/app/evidence.json")
    parser.add_argument("--output-dir", default="/app")
    args = parser.parse_args()
    game = RolloutGame(json.loads(Path(args.input).read_text()))
    result = game.solve()
    report, arrays = outputs(game, *result)
    if game.floor_bad > 1e-9:
        raise RuntimeError("interior calibration violates an exposure floor")
    for group in report["metric_calibrations"].values():
        if any(
            not (len(a) == 2 and min(a) >= 0 and sum(a) <= 1)
            for pair in group.values()
            for a in pair
        ):
            raise RuntimeError("endpoint calibration is outside the joint simplex")
    bank = report["certificate"]
    if not 1 <= len(bank["regret"]) <= 128 or len(bank["safety"]) > 128:
        raise RuntimeError("generated certificate exceeds the public bank limits")
    if (
        sum(term["count"] for term in report["mixture"])
        != game.data["planning"]["rollout_buckets"]
    ):
        raise RuntimeError("integer master returned an invalid bucket total")
    if any(not np.isfinite(value).all() for value in arrays.values()):
        raise RuntimeError("generated witness contains a non-finite value")
    dest = Path(args.output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "evaluation.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    np.savez_compressed(dest / "witnesses.npz", **arrays)


if __name__ == "__main__":
    main()
