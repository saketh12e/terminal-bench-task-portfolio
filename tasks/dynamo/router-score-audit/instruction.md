The language-router package in `/app/lm_router` runs, but its installed scoring and serving audit do not match the published contract. Repair the package so it follows `/app/spec/router_contract.md`, then score `/app/data/eval_batch.jsonl` with the router files under `/app/data` and `/app/model`, including the runtime policy in `/app/model/router_runtime_policy.json` and the calibration feed in `/app/model/calibration_events.jsonl`.

Write these outputs:

`/app/output/predictions.jsonl`: one JSON object per input, sorted by `input_id`, with the exact fields and types defined in `/app/spec/router_contract.md`.

`/app/output/token_score_audit.csv`: the token-level scoring audit defined in `/app/spec/router_contract.md`, including prompt tokens and every candidate-label continuation token.

`/app/output/serving_trace.jsonl`: the per-input serving lineage trace defined in `/app/spec/router_contract.md`.

`/app/output/evaluation_report.json`: the exact summary object defined in `/app/spec/router_contract.md`.

The repaired package should also remain reusable: `lm-router-score --input INPUT --output-dir DIR` must work for another batch with the same schema, and the public helper functions named in the contract must keep their documented return shapes. Do not modify `/app/data`, `/app/model`, or `/app/spec`.
