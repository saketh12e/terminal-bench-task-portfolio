Router contract, version `router-eval-v1`.

Inputs:

- `/app/data/eval_batch.jsonl` contains UTF-8 JSON lines. Each object has `input_id` string, `text` string, `served_at` ISO-8601 string with `Z`, and optional `gold_label` string. A row is labeled only when `gold_label` is a non-empty string. Missing, null, or empty-string `gold_label` values are excluded from `labeled_count` and `accuracy_micro`.
- `/app/data/router_config.json` contains `abstain_label` string, `abstain_margin_micro` int, and `labels` in canonical tie-break order. Each label has `label_id` string, `verbalizers` array of non-empty strings in canonical variant order, and `prior_micro` integer.
- `/app/model/tokenizer.json` contains `vocab`, `bos_token_id`, `unknown_token_id`, and `byte_token_offset`.
- `/app/model/token_scores.json` contains `base_micro`, `transition_micro`, `unknown_base_micro`, and `byte_base_micro`.
- `/app/model/router_runtime_policy.json` contains serving-time policy rules. Each rule has `rule_id`, `target_label`, `target_variant_index`, `effective_from` ISO-8601 string with `Z`, `expires_at` ISO-8601 string with `Z` or null, `if_all_prompt_token_ids`, `if_any_prompt_token_ids`, `if_no_prompt_token_ids`, and `adjustment_micro`.
- `/app/model/calibration_events.jsonl` contains UTF-8 JSON lines for calibration observations. Each object has `calibration_key` string, `event_id` string, `model_version` string, `event_time` ISO-8601 string with `Z`, `sequence` int, `status` string, `target_label` string, `target_variant_index` int, `required_prompt_token_ids` array of ints, `any_prompt_token_ids` array of ints, `blocked_prompt_token_ids` array of ints, `components` array of objects with `name` string and `micro` int, `confidence_ppm` int, and `max_abs_adjustment_micro` int.

Public helper API:

- `load_router(config_path, tokenizer_path, scores_path)` returns a dict with keys `config`, `tokenizer`, `scores`, and `label_order`.
- `normalize_text(text)` returns the canonical string.
- `tokenize_text(text, router_or_tokenizer)` returns token dicts with `token_id` int, `token` string, `position` int, `word_index` int, and `byte_fallback` bool.
- `score_candidate(message_tokens, label, router)` returns the best base verbalizer for one label. The returned dict has `label_id`, `variant_index`, `verbalizer`, `raw_micro`, `token_count`, `normalized_micro`, `prior_micro`, `adjusted_micro`, `tokens`, and `variants`.
- Each item in `score_candidate(...)[ "tokens" ]` and in each `variants` item's `tokens` list has `token` string, `token_id` int, `position` int, `prev_token_id` int, `base_micro` int, `transition_micro` int, `running_raw_micro` int, and `byte_fallback` bool.
- `load_runtime_policy(policy_path)` returns the parsed runtime policy.
- `select_runtime_policy(policy, served_at)` returns a policy dict with the same `policy_id` and the rules active as of `served_at`, preserving original rule order.
- `load_calibration_events(events_path)` returns the parsed calibration event rows.
- `compile_calibration_events(events, model_version)` returns a dict with `model_version` string and `events` array. Each event in `events` is a compiled timeline row for the requested model version, not a global current-only row. It preserves `calibration_key`, `event_id`, `model_version`, `event_time`, `sequence`, `status`, `target_label`, `components`, `confidence_ppm`, and `max_abs_adjustment_micro`; casts `target_variant_index`, `required_prompt_token_ids`, `any_prompt_token_ids`, and `blocked_prompt_token_ids` to ints; and adds integer `adjustment_micro`.
- `select_calibration_events(calibration, served_at)` returns a dict with `model_version` string and `events` array. Its `events` array contains the active current event per `calibration_key` as of `served_at`, sorted by `calibration_key`.
- `calibration_events_sha256(events_path)` returns the SHA-256 hex digest of the exact bytes in `/app/model/calibration_events.jsonl`.
- `apply_runtime_policy(message_tokens, candidate, policy, calibration)` returns a candidate with all variants decorated for runtime ranking.
- `build_serving_trace(predictions, audit_rows, trace_contexts)` returns the serving trace rows described below. `trace_contexts` is keyed by `input_id`; each value has `served_at` string, `policy_rules` array selected for that input, and `calibration_events` array selected for that input.
- `score_runtime_batch(batch_path, router, policy, policy_path, calibration, calibration_path)` returns `(predictions, audit_rows, serving_trace, evaluation_report)` using runtime ranking. The helper may also accept the old four-argument form by treating calibration as empty.
- `write_runtime_outputs(predictions, audit_rows, serving_trace, evaluation_report, output_dir)` writes the four required files.

Canonical normalization:

1. Apply Unicode NFKC.
2. Casefold.
3. Decompose with NFD, drop all combining marks, then recompose with NFC.
4. Replace every maximal whitespace run with one ASCII space and trim leading or trailing spaces.

Tokenization:

- Split the normalized text on ASCII spaces.
- Word-initial vocabulary pieces start with `^`; continuation pieces do not.
- For each word, segment left to right with greedy longest match. At a word start, try vocabulary pieces beginning with `^`; after that, try bare continuation pieces.
- If no vocabulary piece matches the next character, emit one byte-fallback token per UTF-8 byte of that character. The token string is `<0xHH>` with uppercase hex, the token id is `byte_token_offset + byte_value`, and `byte_fallback` is true.
- Empty text tokenizes to an empty list.

Base scoring:

- Score every verbalizer variant for every label as a conditional continuation after the message tokens. Prompt tokens are audited but never included in the label score.
- For a candidate token, `token_micro = base_micro[token_id] + transition_micro["prev>token_id"]`. Missing base scores use `unknown_base_micro`, except byte-fallback tokens use `byte_base_micro`. Missing transitions are zero.
- The previous token for the first candidate token is the last prompt token, or `bos_token_id` when the prompt is empty. After that, the previous token is the prior candidate token.
- `raw_micro` is the sum of candidate `token_micro` values only.
- `normalized_micro` is `raw_micro / candidate_token_count`, rounded to the nearest integer with half-even ties. The integer unit is one micro-logprob point, so no floating-point comparison is needed.
- `adjusted_micro = normalized_micro + prior_micro`.
- For a single label, choose the best base verbalizer variant by higher `adjusted_micro`, then higher `normalized_micro`, then higher `raw_micro`, then lower `variant_index`.

Runtime policy:

- Runtime ranking is applied after base scores are computed and before label ranking. It does not change `raw_micro`, `normalized_micro`, `prior_micro`, or `adjusted_micro`.
- For each input row, select the runtime policy snapshot using that row's `served_at`. A rule is active when `effective_from <= served_at` and either `expires_at` is null or `served_at < expires_at`.
- An active rule applies to a candidate variant only when `target_label` equals the candidate `label_id`, `target_variant_index` equals the candidate `variant_index`, every id in `if_all_prompt_token_ids` appears in the prompt token ids, at least one id in `if_any_prompt_token_ids` appears when that list is non-empty, and no id in `if_no_prompt_token_ids` appears.
- Prompt token ids are the token ids produced from the input text before any verbalizer tokens are appended. Duplicate prompt ids do not change rule matching.
- For each variant, `policy_rule_ids` is the list of matching `rule_id` strings in file order and `policy_adjustment_micro` is the sum of their `adjustment_micro` integers.

Calibration events:

- Compile calibration events before scoring a batch. Consider only rows whose `model_version` equals `router-eval-v1`; keep all such rows in the compiled timeline after applying the type casts and `adjustment_micro` calculation above.
- For each compiled timeline row, `adjustment_micro` is computed from `components` as follows. Sum the signed component `micro` values, multiply by `confidence_ppm`, divide by `1000000`, and round to the nearest integer using half-even ties. Clamp the result to the inclusive range `[-max_abs_adjustment_micro, max_abs_adjustment_micro]`.
- For each input row, select the calibration snapshot using that row's `served_at`. For each `calibration_key`, consider compiled timeline rows with `event_time <= served_at`, then choose the current row by latest `event_time`, highest `sequence`, and lexicographically highest `event_id`. This final sort key is unique in the provided data. If the current row's `status` is not `active`, that key contributes no selected event for that input.
- A selected event applies to a candidate variant only when `target_label` equals the candidate `label_id`, `target_variant_index` equals the candidate `variant_index`, every id in `required_prompt_token_ids` appears in the prompt token ids, at least one id in `any_prompt_token_ids` appears when that list is non-empty, and no id in `blocked_prompt_token_ids` appears.
- For each variant, `calibration_event_ids` is the list of matching `event_id` strings in selected event order, sorted by `calibration_key`, and `calibration_adjustment_micro` is the sum of their compiled `adjustment_micro` integers.
- `runtime_adjusted_micro = adjusted_micro + policy_adjustment_micro + calibration_adjustment_micro`.
- For a single label, choose the runtime verbalizer variant by higher `runtime_adjusted_micro`, then higher `adjusted_micro`, then higher `normalized_micro`, then higher `raw_micro`, then lower `variant_index`.
- Rank labels by their selected runtime variant: higher `runtime_adjusted_micro`, then higher `adjusted_micro`, then higher `normalized_micro`, then higher `raw_micro`, then earlier label order from `/app/data/router_config.json`.
- `margin_micro = top runtime_adjusted_micro - runner-up runtime_adjusted_micro`.
- Predict `ABSTAIN` when `margin_micro <= abstain_margin_micro`; otherwise predict the top label. `abstain_margin_micro` and `abstain_label` come from `/app/data/router_config.json`. The abstain comparison is exact integer comparison.

`/app/output/predictions.jsonl` schema:

- One object per input, sorted by `input_id`.
- Fields: `input_id` string, `predicted_label` string, `top_label` string, `runner_up_label` string, `abstained` bool, `margin_micro` int, `label_scores` array.
- Each `label_scores` item has `label_id` string, `variant_index` int, `verbalizer` string, `raw_micro` int, `token_count` int, `normalized_micro` int, `prior_micro` int, `adjusted_micro` int, `policy_rule_ids` array of strings, `policy_adjustment_micro` int, `calibration_event_ids` array of strings, `calibration_adjustment_micro` int, and `runtime_adjusted_micro` int.
- `label_scores` is sorted by the runtime ranking rule above.

`/app/output/token_score_audit.csv` schema:

- Header exactly: `input_id,label_id,variant_index,row_type,position,token_id,token,prev_token_id,base_micro,transition_micro,included_in_score,running_raw_micro,policy_rule_ids,policy_adjustment_micro,calibration_event_ids,calibration_adjustment_micro,runtime_adjusted_micro`.
- Include prompt rows and every candidate continuation token for every verbalizer variant of every label, not only the predicted label and not only the selected variant.
- Prompt rows use `row_type=prompt`, empty `label_id`, empty `variant_index`, `included_in_score=false`, `base_micro=0`, `transition_micro=0`, and empty `prev_token_id`, `running_raw_micro`, `policy_rule_ids`, `policy_adjustment_micro`, `calibration_event_ids`, `calibration_adjustment_micro`, and `runtime_adjusted_micro`.
- Candidate rows use `row_type=candidate`, integer-string `variant_index`, `included_in_score=true`, `policy_rule_ids` joined by `|` in policy file order, `calibration_event_ids` joined by `|` in compiled event order, and integer strings for the score fields.
- Sort rows by `input_id`, then `row_type`, then `label_id`, then numeric `variant_index`, then numeric `position`. With ASCII order this places candidate rows before prompt rows. Prompt rows sort after candidate rows because their `row_type` is `prompt`.

`/app/output/serving_trace.jsonl` schema:

- One object per input, sorted by `input_id`.
- Fields: `input_id` string, `served_at` string, `top_label` string, `predicted_label` string, `abstained` bool, `policy_snapshot_rule_count` int, `calibration_snapshot_event_count` int, `policy_rule_ids` array of strings, `calibration_event_ids` array of strings, `policy_snapshot_sha256` string, `calibration_snapshot_sha256` string, `score_vector_sha256` string, `audit_span_sha256` string, `selected_variant_signature` string, and `lineage_sha256` string.
- `policy_snapshot_rule_count` is the number of runtime policy rules active for that input after applying the `served_at` window, whether or not each rule matches a candidate.
- `calibration_snapshot_event_count` is the number of active current calibration events selected for that input after the per-key current-record rule, whether or not each event matches a candidate.
- `policy_rule_ids` is the de-duplicated list of policy rule ids that matched at least one selected label-score variant for that input. Preserve first encounter order while scanning the input's `label_scores` array from top rank to bottom rank, and each score's `policy_rule_ids` array from left to right.
- `calibration_event_ids` follows the same first-encounter rule over the input's `label_scores` array and each score's `calibration_event_ids` array.
- `policy_snapshot_sha256`, `calibration_snapshot_sha256`, `score_vector_sha256`, and `audit_span_sha256` are SHA-256 hex strings over the corresponding parsed object or array serialized as compact JSON with sorted object keys and ASCII escaping. `policy_snapshot_sha256` uses the active policy `rules` array for that input. `calibration_snapshot_sha256` uses the selected calibration `events` array for that input. `score_vector_sha256` uses the input's `label_scores` array. `audit_span_sha256` uses all parsed audit rows for that input after global audit sorting.
- `selected_variant_signature` joins the input's ranked selected variants with `|`. Each segment is `label_id:variant_index:runtime_adjusted_micro`.
- `lineage_sha256` is the SHA-256 hex digest of the serving trace row before `lineage_sha256` is added, serialized as compact JSON with sorted object keys and ASCII escaping.

`/app/output/evaluation_report.json` schema:

- Object fields: `schema_version` string, `runtime_policy_id` string, `runtime_policy_sha256` string, `calibration_events_sha256` string, `calibration_current_count` int, `calibration_adjustment_count` int, `prediction_count` int, `label_count` int, `abstention_count` int, `audit_row_count` int, `policy_adjustment_count` int, `labeled_count` int, `correct_labeled_count` int, `accuracy_micro` int, `mean_margin_micro` int, `predictions_sha256` string, `audit_sha256` string, `serving_trace_count` int, and `serving_trace_sha256` string.
- `runtime_policy_id` is `policy_id` from `/app/model/router_runtime_policy.json`.
- `runtime_policy_sha256` is the SHA-256 hex digest of the exact bytes in `/app/model/router_runtime_policy.json`.
- `calibration_events_sha256` is the SHA-256 hex digest of the exact bytes in `/app/model/calibration_events.jsonl`.
- `calibration_current_count` is the number of active current events selected at the latest `served_at` timestamp in the scored batch.
- `calibration_adjustment_count` is the number of candidate variants across all inputs whose `calibration_adjustment_micro` is not zero. It counts variants, not rows.
- `policy_adjustment_count` is the number of candidate variants across all inputs whose `policy_adjustment_micro` is not zero. It counts variants, not rows.
- `labeled_count` is the number of input rows whose `gold_label` is a non-empty string.
- `accuracy_micro` is `correct_labeled_count / labeled_count * 1000000`, rounded with half-even integer division. If `labeled_count` is zero, `accuracy_micro` is zero.
- `mean_margin_micro` is the arithmetic mean of all margins, rounded with half-even integer division.
- `serving_trace_count` is the number of rows in `/app/output/serving_trace.jsonl`.
- The three output digests are SHA-256 hex strings over the parsed prediction, audit row, or serving trace arrays serialized as compact JSON with sorted object keys and ASCII escaping.
