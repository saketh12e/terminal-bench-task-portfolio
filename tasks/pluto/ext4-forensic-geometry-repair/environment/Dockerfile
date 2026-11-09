FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DIR=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq tmux asciinema \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.3.4

COPY forensic_workspace.py bench_fixtures.py recovery_batch_runner.py \
    sector_anchor_resolver.py partition_span_engine.py boot_slot_writer.py \
    backup_sb_lane.py gpt_type_encoder.py evidence_digest_checker.py \
    mount_gate_evaluator.py lane_token_resolver.py binding_lane_resolver.py \
    finalize_dispatch_bridge.py registry_token_table.py json_report_emitter.py \
    output_finalize_pass.py repair_attestation_sync.py \
    geometry_seal_lane.py \
    trace_chain_seal.py registry_token_table.py backup_slot_patcher.py \
    sector_trace_table.py dd_rescue_stub.py ./

RUN python3 bench_fixtures.py && mkdir -p /app/output /app/work /logs/verifier
