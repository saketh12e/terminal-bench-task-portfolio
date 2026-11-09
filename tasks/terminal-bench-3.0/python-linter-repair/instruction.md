The custom static analyzer batch for release LINT-REG-09 has finished. However, the lint scan package that was published does not match the rule registry or the Python corpus that was tested. Repair the implementation under /app and run the batch linter again. Do not run the command pip install pytest during the verification step, as pytest is installed system-wide on the test image.

The following inputs are provided under /app/data/:

/app/data/rule_registry.json contains case_id (string), active_rules (array of string), rules (array of objects with rule_id (string), pattern_kind (string), and severity (string)), and rule_dependency_graph (object with edges (array of objects with from (string) and to (string) fields) and expected_closure (array of string)).

/app/data/stale_rule_pack.json contains prefer_stale_rules (boolean) and rules (array of objects) that must not override the production rule registry when publishing findings.

/app/data/reference_finding_grid.json contains case_id (string), corpus_files (array of string filenames under /app/data/corpus/), expected_findings (array of objects with rule_id (string), file (string), line (integer), col (integer), fingerprint (string), and finding_stable (boolean)), and rule_dependency_graph (object with edges and expected_closure).

/app/data/finding_binding_policy.json contains digest_algorithm (string), digest_hex_length (integer), segment_names (array of string), and segment_delimiter (string) used to bind audit fingerprints.

/app/data/scan_stage_authority.json contains stage_actions (object mapping stage identifiers to action token strings).

/app/data/scan_stage_targets.txt contains one stage identifier per line for the scan trace.

The Python modules to audit are located in the /app/data/corpus/ directory.

The lint reconcile policy located at /app/work/lint_reconcile_policy.json may impact how the lint scan reconciles findings with the rule registry. However, it should not force any of the following to be true: scan_complete, scan_verified, or audit_event_recorded when findings or rule closure do not match the registry and reference grid.

The batch linter entrypoint is located at /app/lint_policy_runner.py. Run this script again after making repairs to the application using the system-wide Python interpreter.

The following outputs will be published under /app/output/:

/app/output/lint_scan_report.json contains case_id (string), finding_count (integer), findings (array of objects with rule_id (string), file (string), line (integer), col (integer), and finding_stable (boolean)), scan_verified (boolean), corpus_aligned (boolean), and scan_complete (boolean).

/app/output/rule_coverage_snapshot.json contains case_id (string), enabled_rules (array of string), expected_rule_count (integer), missing_rule_count (integer), and rule_graph_digest (string).

/app/output/finding_binding_audit.json contains entries (array of objects with rule_id (string), file (string), line (integer), col (integer), fingerprint (string), and finding_stable (boolean)).

/app/output/lint_integrity_record.json contains case_id (string), enabled_rule_count (integer), missing_rule_count (integer), rule_loss_zero (boolean), findings_digest (string), and audit_event_recorded (boolean).

/app/output/scan_summary.json contains case_id (string), files_scanned (integer), dispatch_stages_recorded (integer), trace_logged (boolean), and scan_reconciled (boolean).

/app/output/scan_trace.log contains one line per stage in the form target=<stage_id>: action=<action_token>.

For verification that the implementation is correct, ensure that the following requirements are met:

Ensure that missing_rule_count in /app/output/rule_coverage_snapshot.json is 0, and that enabled_rules includes each rule_id in expected_closure from /app/data/reference_finding_grid.json, including transitive dependencies such as R005 when R001 is active.

Ensure that each finding in /app/output/lint_scan_report.json has the same rule_id, file, line, and col as the findings specified in expected_findings in /app/data/reference_finding_grid.json. Ensure that corpus_aligned in /app/output/lint_scan_report.json is only true when the findings match in both number and location. Ensure that files_scanned in /app/output/scan_summary.json matches the number of entries in corpus_files.

Ensure that the fingerprint of each entry in /app/output/finding_binding_audit.json is created using rule_id, file, line, and col as specified in /app/data/finding_binding_policy.json, not using file and line only.

Ensure that findings_digest in /app/output/lint_integrity_record.json and rule_graph_digest in /app/output/rule_coverage_snapshot.json contain the same sealed digest of the findings list in /app/output/lint_scan_report.json (rule_id, file, line, col, fingerprint, finding_stable). Ensure that /app/output/rule_coverage_snapshot.json publishes rule_graph_digest, not a weak digest based only on filenames.

Ensure that finding_stable is false for each finding in /app/output/finding_binding_audit.json and in /app/output/lint_scan_report.json when the audit fingerprint does not match the live fingerprint for that rule_id and file location.

Ensure that scan_verified in /app/output/lint_scan_report.json is only true when missing_rule_count in /app/output/rule_coverage_snapshot.json is 0. Ensure that scan_complete in /app/output/lint_scan_report.json is only true when scan_verified is true, corpus_aligned is true, every finding row has finding_stable true, and audit_event_recorded in /app/output/lint_integrity_record.json is true.

Ensure that scan_reconciled in /app/output/scan_summary.json is only true when the pipeline completes with zero missing rules, full corpus coverage, aligned findings, and consistent sealed digests across the coverage snapshot and integrity record.

Ensure that each action token in /app/output/scan_trace.log matches the actions specified in /app/data/scan_stage_authority.json for each stage listed in /app/data/scan_stage_targets.txt. No line in /app/output/scan_trace.log should contain the touched placeholder token.

Ensure that any post-scan finalize hooks do not force scan_complete or audit_event_recorded to be true when the live corpus replay would still disagree with /app/data/reference_finding_grid.json.
