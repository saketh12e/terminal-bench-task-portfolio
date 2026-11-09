#!/bin/bash
set -euo pipefail
#
# Runs inside the SHARED environment image (environment/Dockerfile) — canonical TB2 has no
# separate verifier image. pytest is baked into environment/Dockerfile, so do NOT install or
# download anything here — verify-time setup is rejected by the static checks.
#
# Put your pytest files (e.g. test_outputs.py) in tests/ and run them below. Harbor overlays
# tests/ at /tests only at verify time, so keep ground truth / expected outputs in tests/
# (never in environment/, where the agent could read them).
# --ctrf writes a standard JSON report; write 1/0 to /logs/verifier/reward.txt.
# The local QC runner uses source_mutations.json for the named wrong-method controls.
mkdir -p /logs/verifier
echo 0 > /logs/verifier/reward.txt
chown -R root:root /tests
chmod 700 /tests
if [ -d /solution ]; then
  chown -R root:root /solution
  chmod 700 /solution
  test "$(stat -c '%u' /solution)" = 0
  test "$(stat -c '%a' /solution)" = 700
fi
cd /tests
unset PYTEST_ADDOPTS PYTEST_PLUGINS PYTHONPATH
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
set +e
timeout --signal=TERM --kill-after=5s 280s \
  /usr/local/bin/python3 -I -m pytest -p ctrf.main -c /dev/null --rootdir=/tests --confcutdir=/tests \
  --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA
status=$?
set -e
final_status=0
if [ ! -s /logs/verifier/ctrf.json ]; then
  final_status=2
elif [ "$status" -eq 1 ]; then
  echo 0 > /logs/verifier/reward.txt
elif [ "$status" -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  final_status=$status
fi
exit "$final_status"
