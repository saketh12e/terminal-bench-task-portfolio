Repair `/app/feature_bundle.py`. It builds a leakage-safe feature bundle for an event-driven training pipeline, but the existing implementation makes several temporal and split-boundary mistakes.

The normative input and output contract is `/app/data/feature_window_contract.md`. Read `/app/data/events.jsonl` and `/app/data/policy.json`, then write `/app/output/feature_bundle.jsonl` and `/app/output/feature_manifest.json` exactly as specified by that contract. The JSONL bundle must contain one record for every live decision event; the manifest must describe the same bundle and its train-only normalizer.

Inputs may be shuffled, may contain corrected revisions of earlier records, and may contain events that share an event timestamp. The result must therefore depend on the contract's revision, event-time, window-boundary, split, and normalization rules, not on physical line order. Do not alter `/app/data/*`. Invalid input must fail before either required output artifact is created.

The repaired program must also support the documented interrupted/resumed execution contract. During resume, the input file intentionally contains only the unseen suffix, so correct final artifacts require recovering the validated prefix from the checkpoint.
