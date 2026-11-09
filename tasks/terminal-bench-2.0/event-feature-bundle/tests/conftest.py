"""Check the delivered bundle before behavioral tests replace their working inputs."""
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest


def regular_bytes(path):
    for ancestor in (path, *path.parents):
        assert not ancestor.is_symlink(), f'symlink artifact path: {ancestor}'
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        assert stat.S_ISREG(os.fstat(descriptor).st_mode), f'nonregular artifact: {path}'
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


@pytest.fixture(scope='session', autouse=True)
def submitted_bundle_matches_protected_visible_inputs(request):
    """Required submitted files and unchanged visible inputs precede fresh hidden runs."""
    app = Path('/app')
    events_data = regular_bytes(app / 'data/events.jsonl')
    policy_data = regular_bytes(app / 'data/policy.json')
    assert hashlib.sha256(events_data).hexdigest() == '3713d93bfa61272a10fa642f76bc77894157d26fefcaeb93c941d618f44a4106', 'modified event input'
    assert hashlib.sha256(policy_data).hexdigest() == 'f65c1029761d5a5dab11dd35c8deeb9e827b6374bb15d2b5b633dea56c6e13ca', 'modified policy input'
    regular_bytes(app / 'feature_bundle.py')
    regular_bytes(app / 'output/feature_bundle.jsonl')
    regular_bytes(app / 'output/feature_manifest.json')
    # Expectations use the already hash-verified bytes, never a second mutable read.
    events = [json.loads(line) for line in events_data.splitlines()]
    policy = json.loads(policy_data)
    verifier = request.session.items[0].module
    verifier.assert_outputs(*verifier.oracle(events, policy))
