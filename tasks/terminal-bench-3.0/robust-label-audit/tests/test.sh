#!/bin/bash
set -uo pipefail
mkdir -p /logs/verifier
chmod 700 /logs/verifier
printf '0' > /logs/verifier/reward.txt
cd /tests || exit 0
unset PYTHONPATH PYTEST_ADDOPTS PYTEST_PLUGINS
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
python3 -I -m pytest -x -c /dev/null -p ctrf --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
result=$?
if [ "$result" -eq 0 ]; then printf '1' > /logs/verifier/reward.txt; fi
exit 0
