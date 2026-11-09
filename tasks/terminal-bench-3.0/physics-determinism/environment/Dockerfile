FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_DIR=/app

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends jq tmux asciinema \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pytest==8.3.4

COPY sim_workspace.py bench_fixtures.py reference_frame_digests_seed.json \
    contact_graph.py impulse_accumulator.py integrator_step.py frame_encoder.py \
    parallel_guard.py twin_run_harness.py scenario_loader.py float_kahan_stub.py \
    stability_report.py physics_sim_runner.py ./

RUN python3 bench_fixtures.py && mkdir -p /app/output /app/work /logs/verifier
