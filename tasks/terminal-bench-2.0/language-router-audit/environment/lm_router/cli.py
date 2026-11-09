import argparse
from pathlib import Path

from lm_router.calibration import compile_calibration_events, load_calibration_events
from lm_router.publisher import finalize_runtime_outputs
from lm_router.runtime import load_runtime_policy, score_runtime_batch, write_runtime_outputs
from lm_router.scorer import load_router


def _default_path(*parts):
    app_path = Path("/app", *parts)
    if app_path.exists() or Path("/app").exists():
        return str(app_path)
    return str(Path.cwd().joinpath(*parts))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=_default_path("data", "eval_batch.jsonl"))
    parser.add_argument("--output-dir", default=_default_path("output"))
    parser.add_argument("--config", default=_default_path("data", "router_config.json"))
    parser.add_argument("--tokenizer", default=_default_path("model", "tokenizer.json"))
    parser.add_argument("--scores", default=_default_path("model", "token_scores.json"))
    parser.add_argument("--policy", default=_default_path("model", "router_runtime_policy.json"))
    parser.add_argument("--calibration-events", default=_default_path("model", "calibration_events.jsonl"))
    args = parser.parse_args(argv)

    router = load_router(args.config, args.tokenizer, args.scores)
    policy = load_runtime_policy(args.policy)
    calibration = compile_calibration_events(load_calibration_events(args.calibration_events), "router-eval-v1")
    predictions, audit_rows, report = score_runtime_batch(
        args.input,
        router,
        policy,
        args.policy,
        calibration,
        args.calibration_events,
    )
    write_runtime_outputs(predictions, audit_rows, report, Path(args.output_dir))
    finalize_runtime_outputs(Path(args.output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
