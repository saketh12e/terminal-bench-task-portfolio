#!/bin/bash
set -euo pipefail

rm -rf /app/settlement_engine
cp -R /solution/settlement_engine /app/settlement_engine
cp /solution/settlement_pipeline.py /app/settlement_pipeline.py
python3 /app/settlement_pipeline.py --input-dir /app/data/current_batch --output-dir /app/output
