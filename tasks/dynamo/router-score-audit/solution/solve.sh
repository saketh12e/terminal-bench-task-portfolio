#!/bin/bash
set -euo pipefail

cp /solution/lm_router/scorer.py /app/lm_router/scorer.py
cp /solution/lm_router/calibration.py /app/lm_router/calibration.py
cp /solution/lm_router/runtime.py /app/lm_router/runtime.py
cp /solution/lm_router/publisher.py /app/lm_router/publisher.py
cp /solution/lm_router/cli.py /app/lm_router/cli.py
lm-router-score --input /app/data/eval_batch.jsonl --output-dir /app/output
