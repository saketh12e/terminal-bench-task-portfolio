FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DIR=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq tmux asciinema \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.3.4

COPY lint_store_contract.py fixture_seed.py lint_policy_runner.py lint_scan_physics.py \
    rule_registry_loader.py ast_visit_dispatch_bridge.py rule_pattern_merge_lane.py \
    rule_pattern_authority.py rule_closure_lane.py corpus_expansion_lane.py \
    finding_binding_compiler.py lint_scan_exporter.py run_post_scan_finalize.py \
    finding_coverage_digest.py integrity_digest_seal.py ./

RUN python3 fixture_seed.py && mkdir -p /app/output /app/work /logs/verifier
