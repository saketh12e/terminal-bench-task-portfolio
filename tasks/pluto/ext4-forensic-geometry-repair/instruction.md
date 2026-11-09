# Case DF-INC-09 forensic disk recovery batch

The recovery batch at `/app` exits successfully, but the system-wide verifier rejects the published artifacts for Case DF-INC-09.

Run the system-wide verifier after your fix. `pip install` is already in the image; do not install additional Python packages. The entry script is `recovery_batch_runner.py`. It reads `/app/data/incident_disk.img`, `/app/data/repair_step_manifest.txt`, and `/app/data/layout_registry.json`. Golden geometry and carve digest are in `/app/data/reference_geometry.json`.

## Required outputs

The verifier reads `/app/output/reconstructed_mbr.bin`, `/app/output/patched_disk.img`, `/app/output/geometry_attestation.json`, `/app/output/carve_verdict.json`, `/app/output/fsck_readiness.json`, `/app/output/repair_summary.json`, and `/app/output/repair_sector_trace.log`.

| Artifact | Contract |
|----------|----------|
| `/app/output/reconstructed_mbr.bin` | Exactly 512 bytes. Bytes 510–511 are `0x55` `0xAA`. Partition entry at offset 446 has type `0x83`, `lba_start` (uint32 little-endian) **2048**, and `sector_count` (uint32 little-endian) matching `/app/data/reference_geometry.json`. |
| `/app/output/patched_disk.img` | Same byte length as `/app/data/incident_disk.img`. First 512 bytes equal `reconstructed_mbr.bin`. After the batch finishes, backup superblock at `backup_superblock_offset` from `/app/data/layout_registry.json` must have magic `0xEF53`, block size **4096**, and `blocks_count` / `inodes_count` matching `/app/data/reference_geometry.json` (on-disk bytes, not JSON alone). |
| `/app/output/geometry_attestation.json` | `case_id` (string) **DF-INC-09**; `repair_complete` (bool) **true**; `lba_start`, `sector_count`, `blocks_count`, `inodes_count` (int) match reference and on-disk fields; `fsck_ready` (bool) **true** and equal to `/app/output/fsck_readiness.json` `fsck_ready`; `disk_probe_ok` (bool) **true** iff the live patched-disk probe passes (same criteria as `reference_geometry_ok`). |
| `/app/output/carve_verdict.json` | `carve_hash_match` (bool) **true**; `expected_sha256` and `actual_sha256` (64-char hex) equal and match `carve_sha256` in reference. |
| `/app/output/fsck_readiness.json` | `fsck_ready` and `mount_ready` (bool) **true**; must reflect live MBR signature, backup superblock fields, and carve hash (not hardcoded when checks fail). |
| `/app/output/repair_summary.json` | `case_id` (string) **DF-INC-09**; `steps_recorded` (int) **9**; `trace_logged` (bool) **true**; `reference_geometry_ok` (bool) **true** per live patched-disk probe; `trace_chain_digest` (string, 64-char hex) is SHA-256 of raw `/app/output/repair_sector_trace.log` bytes after finalization; `case_envelope_digest` (string, 64-char hex) is SHA-256 of the byte concatenation (in order): `/app/output/reconstructed_mbr.bin`, then `/app/output/repair_sector_trace.log`, then the carve span bytes from `/app/output/patched_disk.img` defined by `carve_offset` and `carve_length` in the layout registry. |
| `/app/output/repair_sector_trace.log` | Nine lines `sector=<n> op=<verb>`, **n** = 1…9. Each `verb` equals the compiled binding for that manifest step: read `/app/data/repair_step_manifest.txt` in order and resolve tokens from the JSON file named by `binding_lane` in `/app/data/layout_registry.json` (not from the registry’s embedded `step_verbs` map, not from obsolete layout policy JSON, and not from work-process verb overlay files under `/app/data/`). Finalization must reconcile the trace from that binding after disk publish. |

Do not wire `dd_rescue_stub.py` into `recovery_batch_runner.py`.
