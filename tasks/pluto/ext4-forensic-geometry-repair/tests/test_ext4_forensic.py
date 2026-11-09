from __future__ import annotations

import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(os.environ.get("APP_DIR", "/app"))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from forensic_workspace import (  # noqa: E402
    CARVE_VERDICT_PATH,
    DISK_IMAGE_PATH,
    FSCK_READINESS_PATH,
    GEOMETRY_ATTESTATION_PATH,
    LAYOUT_REGISTRY_PATH,
    PATCHED_DISK_PATH,
    RECONSTRUCTED_MBR_PATH,
    REFERENCE_GEOMETRY_PATH,
    REPAIR_SECTOR_TRACE_PATH,
    REPAIR_SUMMARY_PATH,
    SUBJECT_CASE_ID,
)

PYTHON_BIN = os.environ.get("PYTHON_BIN", "python")
DATA_DIR = APP_DIR / "data"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def run_pipeline(*, reseed: bool = False) -> subprocess.CompletedProcess[str]:
    if reseed:
        from bench_fixtures import main as seed_main

        seed_main()
    for path in (
        PATCHED_DISK_PATH,
        RECONSTRUCTED_MBR_PATH,
        GEOMETRY_ATTESTATION_PATH,
        CARVE_VERDICT_PATH,
        FSCK_READINESS_PATH,
        REPAIR_SUMMARY_PATH,
        REPAIR_SECTOR_TRACE_PATH,
    ):
        if path.exists():
            path.unlink()
    return subprocess.run(
        [PYTHON_BIN, "recovery_batch_runner.py"],
        cwd=APP_DIR,
        text=True,
        capture_output=True,
        timeout=120,
    )


def ensure_run() -> None:
    result = run_pipeline()
    assert result.returncode == 0, result.stdout + result.stderr


def reference() -> dict:
    return load_json(REFERENCE_GEOMETRY_PATH)


def mbr_lba_fields(mbr: bytes, entry_offset: int = 446) -> tuple[int, int, int]:
    part_type = mbr[entry_offset + 4]
    lba_start = struct.unpack_from("<I", mbr, entry_offset + 8)[0]
    sector_count = struct.unpack_from("<I", mbr, entry_offset + 12)[0]
    return part_type, lba_start, sector_count


# --- smoke ---


def test_runner_exits_zero():
    assert run_pipeline().returncode == 0


def test_patched_disk_exists():
    ensure_run()
    assert PATCHED_DISK_PATH.exists()


def test_reconstructed_mbr_exists():
    ensure_run()
    assert RECONSTRUCTED_MBR_PATH.exists()


def test_geometry_attestation_exists():
    ensure_run()
    assert GEOMETRY_ATTESTATION_PATH.exists()


def test_carve_verdict_exists():
    ensure_run()
    assert CARVE_VERDICT_PATH.exists()


def test_fsck_readiness_exists():
    ensure_run()
    assert FSCK_READINESS_PATH.exists()


def test_repair_summary_exists():
    ensure_run()
    assert REPAIR_SUMMARY_PATH.exists()


def test_sector_trace_exists():
    ensure_run()
    assert REPAIR_SECTOR_TRACE_PATH.exists()


def test_case_id_subject():
    ensure_run()
    assert load_json(GEOMETRY_ATTESTATION_PATH)["case_id"] == SUBJECT_CASE_ID


def test_repair_complete_flag():
    ensure_run()
    assert load_json(GEOMETRY_ATTESTATION_PATH)["repair_complete"] is True


# --- MBR / geometry ---


def test_mbr_signature_bytes():
    ensure_run()
    mbr = RECONSTRUCTED_MBR_PATH.read_bytes()
    assert mbr[510] == 0x55 and mbr[511] == 0xAA


def test_mbr_partition_type_linux():
    ensure_run()
    mbr = RECONSTRUCTED_MBR_PATH.read_bytes()
    part_type, _, _ = mbr_lba_fields(mbr)
    assert part_type == 0x83


def test_mbr_lba_start_reference():
    ensure_run()
    mbr = RECONSTRUCTED_MBR_PATH.read_bytes()
    _, lba, _ = mbr_lba_fields(mbr)
    assert lba == reference()["lba_start"]


def test_mbr_sector_count_reference():
    ensure_run()
    mbr = RECONSTRUCTED_MBR_PATH.read_bytes()
    _, _, sectors = mbr_lba_fields(mbr)
    assert sectors == reference()["sector_count"]


def test_geometry_lba_start():
    ensure_run()
    att = load_json(GEOMETRY_ATTESTATION_PATH)
    assert att["lba_start"] == reference()["lba_start"]


def test_geometry_sector_count():
    ensure_run()
    att = load_json(GEOMETRY_ATTESTATION_PATH)
    assert att["sector_count"] == reference()["sector_count"]


def test_geometry_blocks_count():
    ensure_run()
    att = load_json(GEOMETRY_ATTESTATION_PATH)
    assert att["blocks_count"] == reference()["blocks_count"]


def test_geometry_inodes_count():
    ensure_run()
    att = load_json(GEOMETRY_ATTESTATION_PATH)
    assert att["inodes_count"] == reference()["inodes_count"]


def test_geometry_fsck_ready_true():
    ensure_run()
    assert load_json(GEOMETRY_ATTESTATION_PATH)["fsck_ready"] is True


def test_reference_geometry_ok_summary():
    ensure_run()
    assert load_json(REPAIR_SUMMARY_PATH)["reference_geometry_ok"] is True


# --- superblock backup ---


def test_backup_superblock_magic():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    magic = struct.unpack_from("<H", disk, int(reg["backup_superblock_offset"]) + 0x38)[0]
    assert magic == 0xEF53


def test_backup_block_size_4096():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    bs = struct.unpack_from("<I", disk, int(reg["backup_superblock_offset"]) + 0x18)[0]
    assert bs == 4096


def test_backup_blocks_count_reference():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    blocks = struct.unpack_from("<I", disk, int(reg["backup_superblock_offset"]) + 0x4)[0]
    assert blocks == reference()["blocks_count"]


def test_backup_inodes_count_reference():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    inodes = struct.unpack_from("<I", disk, int(reg["backup_superblock_offset"]) + 0x28)[0]
    assert inodes == reference()["inodes_count"]


def test_primary_superblock_not_wiped():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    magic = struct.unpack_from("<H", disk, int(reg["primary_superblock_offset"]) + 0x38)[0]
    assert magic == 0xEF53


# --- carve ---


def test_carve_hash_match_true():
    ensure_run()
    assert load_json(CARVE_VERDICT_PATH)["carve_hash_match"] is True


def test_carve_expected_sha256_hex():
    ensure_run()
    digest = load_json(CARVE_VERDICT_PATH)["expected_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_carve_actual_matches_expected():
    ensure_run()
    verdict = load_json(CARVE_VERDICT_PATH)
    assert verdict["actual_sha256"] == verdict["expected_sha256"]


def test_carve_matches_reference_file():
    ensure_run()
    verdict = load_json(CARVE_VERDICT_PATH)
    assert verdict["expected_sha256"] == reference()["carve_sha256"]


# --- fsck / mount readiness ---


def test_fsck_ready_true():
    ensure_run()
    assert load_json(FSCK_READINESS_PATH)["fsck_ready"] is True


def test_mount_ready_true():
    ensure_run()
    assert load_json(FSCK_READINESS_PATH)["mount_ready"] is True


def test_fsck_matches_geometry_attestation():
    ensure_run()
    fsck = load_json(FSCK_READINESS_PATH)["fsck_ready"]
    att = load_json(GEOMETRY_ATTESTATION_PATH)["fsck_ready"]
    assert fsck == att


def test_mount_ready_when_carve_ok():
    ensure_run()
    assert load_json(CARVE_VERDICT_PATH)["carve_hash_match"] is True
    assert load_json(FSCK_READINESS_PATH)["mount_ready"] is True


def test_mount_not_ready_when_carve_mismatch():
    ensure_run()
    if not load_json(CARVE_VERDICT_PATH)["carve_hash_match"]:
        assert load_json(FSCK_READINESS_PATH)["mount_ready"] is False


def test_attestation_fsck_false_when_carve_mismatch():
    ensure_run()
    if not load_json(CARVE_VERDICT_PATH)["carve_hash_match"]:
        assert load_json(GEOMETRY_ATTESTATION_PATH)["fsck_ready"] is False


# --- trace / registry ---


def test_trace_line_count_nine():
    ensure_run()
    lines = [ln for ln in REPAIR_SECTOR_TRACE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 9


def test_trace_sector_format():
    ensure_run()
    for line in REPAIR_SECTOR_TRACE_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            assert re.match(r"^sector=\d+ op=\w+$", line.strip())


def test_sector_trace_excludes_registry_decoy_verbs():
    ensure_run()
    decoys = set(load_json(LAYOUT_REGISTRY_PATH)["step_verbs"].values())
    text = REPAIR_SECTOR_TRACE_PATH.read_text(encoding="utf-8")
    for token in decoys:
        assert f"op={token}" not in text


def test_binding_lane_resolves_nine_compiled_verbs():
    reg = load_json(LAYOUT_REGISTRY_PATH)
    lane_path = DATA_DIR / reg["binding_lane"]
    if not str(lane_path).endswith(".json"):
        lane_path = DATA_DIR / f"{reg['binding_lane']}.json"
    lane = load_json(lane_path)
    assert len(lane["compiled_step_verbs"]) == 9


def test_sector_trace_ops_match_binding_lane():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    lane_path = DATA_DIR / reg["binding_lane"]
    if lane_path.suffix != ".json":
        lane_path = DATA_DIR / f"{reg['binding_lane']}.json"
    verbs = load_json(lane_path)["compiled_step_verbs"]
    manifest = (APP_DIR / "data/repair_step_manifest.txt").read_text(encoding="utf-8").strip().splitlines()
    lines = [ln for ln in REPAIR_SECTOR_TRACE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == len(manifest) == 9
    for idx, (step, line) in enumerate(zip(manifest, lines), start=1):
        assert line.startswith(f"sector={idx} ")
        assert f"op={verbs[step]}" in line


def test_summary_steps_recorded():
    ensure_run()
    assert load_json(REPAIR_SUMMARY_PATH)["steps_recorded"] == 9


def test_summary_trace_logged():
    ensure_run()
    assert load_json(REPAIR_SUMMARY_PATH)["trace_logged"] is True


def test_geometry_disk_probe_ok_when_repair_passes():
    ensure_run()
    assert load_json(GEOMETRY_ATTESTATION_PATH)["disk_probe_ok"] is True


def test_disk_probe_false_when_carve_mismatch():
    ensure_run()
    if not load_json(CARVE_VERDICT_PATH)["carve_hash_match"]:
        assert load_json(GEOMETRY_ATTESTATION_PATH)["disk_probe_ok"] is False


def test_summary_trace_chain_digest_is_hex64():
    ensure_run()
    digest = load_json(REPAIR_SUMMARY_PATH)["trace_chain_digest"]
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_summary_trace_digest_matches_log_bytes():
    ensure_run()
    import hashlib

    expected = hashlib.sha256(REPAIR_SECTOR_TRACE_PATH.read_bytes()).hexdigest()
    assert load_json(REPAIR_SUMMARY_PATH)["trace_chain_digest"] == expected


def test_attestation_blocks_match_backup_on_disk():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    on_disk = struct.unpack_from("<I", disk, int(reg["backup_superblock_offset"]) + 0x4)[0]
    assert load_json(GEOMETRY_ATTESTATION_PATH)["blocks_count"] == on_disk


def test_readiness_fsck_implies_carve_when_true():
    ensure_run()
    if load_json(FSCK_READINESS_PATH)["fsck_ready"]:
        assert load_json(CARVE_VERDICT_PATH)["carve_hash_match"] is True


def test_summary_reference_false_when_carve_mismatch():
    ensure_run()
    if not load_json(CARVE_VERDICT_PATH)["carve_hash_match"]:
        assert load_json(REPAIR_SUMMARY_PATH)["reference_geometry_ok"] is False


def test_dd_rescue_not_wired():
    src = (APP_DIR / "recovery_batch_runner.py").read_text(encoding="utf-8")
    assert "dd_rescue_stub" not in src


def test_finalize_dispatch_wires_binding_lane():
    finalize_src = (APP_DIR / "output_finalize_pass.py").read_text(encoding="utf-8")
    assert "finalize_dispatch_bridge" in finalize_src
    bridge_src = (APP_DIR / "finalize_dispatch_bridge.py").read_text(encoding="utf-8")
    assert "binding_lane_resolver" in bridge_src


def test_runner_publishes_disk_before_finalize():
    src = (APP_DIR / "recovery_batch_runner.py").read_text(encoding="utf-8")
    assert "finalize_case_outputs(" in src
    disk_idx = src.rindex("PATCHED_DISK_PATH.write_bytes")
    fin_idx = src.index("finalize_case_outputs(")
    assert disk_idx < fin_idx


def test_summary_case_envelope_digest_matches_live():
    ensure_run()
    import hashlib

    reg = load_json(LAYOUT_REGISTRY_PATH)
    mbr = RECONSTRUCTED_MBR_PATH.read_bytes()
    trace = REPAIR_SECTOR_TRACE_PATH.read_bytes()
    off = int(reg["carve_offset"])
    ln = int(reg["carve_length"])
    carve = PATCHED_DISK_PATH.read_bytes()[off : off + ln]
    expected = hashlib.sha256(mbr + trace + carve).hexdigest()
    assert load_json(REPAIR_SUMMARY_PATH)["case_envelope_digest"] == expected


def test_sector_trace_finalize_steps_use_lane_bindings():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    lane_path = DATA_DIR / reg["binding_lane"]
    if lane_path.suffix != ".json":
        lane_path = DATA_DIR / f"{reg['binding_lane']}.json"
    verbs = load_json(lane_path)["compiled_step_verbs"]
    text = REPAIR_SECTOR_TRACE_PATH.read_text(encoding="utf-8")
    assert f"op={verbs['report_emit']}" in text
    assert f"op={verbs['finalize']}" in text


def test_disk_image_size_eight_mb():
    assert DISK_IMAGE_PATH.stat().st_size == 8 * 1024 * 1024


def test_patched_disk_same_size():
    ensure_run()
    assert PATCHED_DISK_PATH.stat().st_size == DISK_IMAGE_PATH.stat().st_size


def test_reconstructed_mbr_length_512():
    ensure_run()
    assert RECONSTRUCTED_MBR_PATH.stat().st_size == 512


def test_registry_case_id():
    assert load_json(LAYOUT_REGISTRY_PATH)["case_id"] == SUBJECT_CASE_ID


def test_reference_block_size():
    assert reference()["block_size"] == 4096


def test_trace_first_sector_one():
    ensure_run()
    first = REPAIR_SECTOR_TRACE_PATH.read_text(encoding="utf-8").splitlines()[0].strip()
    assert first.startswith("sector=1 ")


def test_trace_last_sector_nine():
    ensure_run()
    lines = [ln for ln in REPAIR_SECTOR_TRACE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines[-1].startswith("sector=9 ")


def test_patched_disk_mbr_copied_to_image():
    ensure_run()
    mbr = RECONSTRUCTED_MBR_PATH.read_bytes()
    head = PATCHED_DISK_PATH.read_bytes()[:512]
    assert head == mbr


def test_runner_importable():
    import recovery_batch_runner

    assert hasattr(recovery_batch_runner, "main")


def test_carve_verdict_has_actual_field():
    ensure_run()
    assert "actual_sha256" in load_json(CARVE_VERDICT_PATH)


def test_geometry_repair_complete():
    ensure_run()
    assert load_json(GEOMETRY_ATTESTATION_PATH)["repair_complete"] is True


def test_reference_mount_ready():
    assert reference()["mount_ready"] is True


def test_reference_fsck_ready():
    assert reference()["fsck_ready"] is True


def test_registry_sector_size_512():
    assert load_json(LAYOUT_REGISTRY_PATH)["sector_size"] == 512


def test_registry_backup_offset_matches_reference():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    assert reg["backup_superblock_offset"] == reference()["backup_superblock_offset"]


def test_mbr_not_big_endian_lba():
    ensure_run()
    mbr = RECONSTRUCTED_MBR_PATH.read_bytes()
    le = struct.unpack_from("<I", mbr, 454)[0]
    be = struct.unpack_from(">I", mbr, 454)[0]
    assert le == reference()["lba_start"]
    assert be != le or le < 256


def test_superblock_magic_primary():
    ensure_run()
    reg = load_json(LAYOUT_REGISTRY_PATH)
    disk = PATCHED_DISK_PATH.read_bytes()
    assert struct.unpack_from("<H", disk, int(reg["primary_superblock_offset"]) + 0x38)[0] == 0xEF53


def test_attestation_inodes_positive():
    ensure_run()
    assert load_json(GEOMETRY_ATTESTATION_PATH)["inodes_count"] > 0


def test_blocks_less_than_sectors():
    ensure_run()
    att = load_json(GEOMETRY_ATTESTATION_PATH)
    assert att["blocks_count"] < att["sector_count"]


def test_manifest_has_nine_lines():
    lines = (APP_DIR / "data/repair_step_manifest.txt").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 9


def test_registry_carve_length_4096():
    reg = load_json(LAYOUT_REGISTRY_PATH)
    assert int(reg["carve_length"]) == 4096


def test_reference_carve_sha_length():
    assert len(reference()["carve_sha256"]) == 64
