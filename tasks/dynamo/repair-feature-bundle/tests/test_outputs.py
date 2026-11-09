import hashlib, json, math, os, pwd, subprocess, sys
from fractions import Fraction
from pathlib import Path
import pytest

APP = Path('/app'); DATA = APP / 'data'; OUT = APP / 'output'
ARTIFACTS = ('feature_bundle.jsonl', 'feature_manifest.json')
CHECKPOINT = OUT / 'feature_checkpoint.json'
FEATURES = ('click_count', 'purchase_net', 'refund_count', 'open_purchase_amount', 'oldest_open_purchase_age_ms', 'activity_recency_ms', 'purchase_recency_ms', 'prior_decision_count', 'prior_positive_rate')
SUFFIX = {300000: '5m', 900000: '15m', 3600000: '1h'}

def raw_names(windows):
    return tuple(f'{feature}_{SUFFIX[window]}' for window in windows for feature in FEATURES)

def accurate_sum(values):
    """Sum finite fixture numbers as exact binary rationals, then round once.

    This is independent of the submitted program's aggregation algorithm and
    does not inherit the physical input order of a floating-point accumulator.
    Output comparisons still use the contract's existing absolute tolerance.
    """
    return float(sum((Fraction(value) for value in values), Fraction()))

def median(values):
    ordered = sorted(values); middle = len(ordered) // 2
    return float(ordered[middle]) if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0

def unsettled_purchases(history):
    pending = []
    for item in sorted(history, key=lambda value: (value['event_ms'], value['ingest_seq'], value['record_id'])):
        amount = float(item['amount'])
        if item['kind'] == 'purchase' and amount > 0:
            pending.append([item['event_ms'], amount])
        elif item['kind'] == 'refund' and amount > 0:
            remaining = amount
            while remaining > 0 and pending:
                consumed = min(remaining, pending[0][1]); remaining -= consumed; pending[0][1] -= consumed
                if pending[0][1] == 0: pending.pop(0)
    return pending

def event(record_id, revision, entity_id, event_ms, ingest_seq, kind, amount=0.0, target=None, available_ms=None):
    return {'record_id': record_id, 'revision': revision, 'entity_id': entity_id, 'event_ms': event_ms, 'available_ms': event_ms if available_ms is None else available_ms, 'ingest_seq': ingest_seq, 'kind': kind, 'amount': amount, 'target': target}

def base_events():
    return [event('n-c1', 1, 'north', 1000, 8, 'click'), event('n-p1', 1, 'north', 1200, 9, 'purchase', 4.0), event('n-d1', 1, 'north', 1300, 10, 'decision', target=1), event('h-c1', 1, 'hazel', 900, 2, 'click'), event('h-r1', 1, 'hazel', 1100, 3, 'refund', 1.0), event('h-d1', 1, 'hazel', 1300, 4, 'decision', target=0), event('n-c1', 2, 'north', 1000, 12, 'click'), event('r-c1', 1, 'rivulet', 100, 1, 'click'), event('r-d1', 1, 'rivulet', 1300, 5, 'decision', target=1), event('s-c1', 1, 'south', 1100, 6, 'refund'), event('s-d1', 1, 'south', 1500, 7, 'decision', target=0), event('n-d2', 1, 'north', 3601000, 13, 'decision', target=0)]

def oracle(events, policy):
    raw = raw_names(policy['window_ms'])
    versions = {}
    for item in events: versions.setdefault(item['record_id'], []).append(item)
    def choose(candidates):
        greatest = max(item['revision'] for item in candidates)
        winners = [item for item in candidates if item['revision'] == greatest]
        if len(winners) != 1: raise ValueError('equal revision')
        return winners[0]
    live = {record_id: choose(candidates) for record_id, candidates in versions.items()}
    values = list(live.values()); anchors = sorted((x for x in values if x['kind'] == 'decision'), key=lambda x: (x['event_ms'], x['ingest_seq'], x['record_id']))
    rows = []
    for anchor in anchors:
        row = {'anchor_id': anchor['record_id'], 'entity_id': anchor['entity_id'], 'anchor_ms': anchor['event_ms'], 'split': 'test' if anchor['entity_id'] in policy['holdout_entities'] else 'train', 'target': anchor['target']}
        selected = []
        for candidates in versions.values():
            known = [item for item in candidates if item['available_ms'] <= anchor['event_ms']]
            if known:
                item = choose(known)
                if item['entity_id'] == anchor['entity_id'] and item['event_ms'] < anchor['event_ms']: selected.append(item)
        activity = [item for item in selected if item['kind'] in {'click', 'purchase', 'refund'}]
        pending = unsettled_purchases(activity)
        for window in policy['window_ms']:
            suffix = SUFFIX[window]
            lower = anchor['event_ms'] - window
            history = [item for item in activity if lower <= item['event_ms']]
            prior_decisions = [item for item in selected if item['kind'] == 'decision' and lower <= item['event_ms']]
            row[f'click_count_{suffix}'] = sum(x['kind'] == 'click' for x in history)
            row[f'purchase_net_{suffix}'] = accurate_sum(x['amount'] for x in history if x['kind'] == 'purchase')
            row[f'refund_count_{suffix}'] = sum(x['kind'] == 'refund' for x in history)
            window_pending = [item for item in pending if lower <= item[0]]
            open_amount = accurate_sum(balance for _, balance in window_pending); oldest_open_ms = window_pending[0][0] if window_pending else None
            row[f'open_purchase_amount_{suffix}'] = open_amount
            row[f'oldest_open_purchase_age_ms_{suffix}'] = anchor['event_ms'] - oldest_open_ms if oldest_open_ms is not None else window
            row[f'activity_recency_ms_{suffix}'] = anchor['event_ms'] - max((x['event_ms'] for x in history), default=anchor['event_ms'] - window)
            row[f'purchase_recency_ms_{suffix}'] = anchor['event_ms'] - max((x['event_ms'] for x in history if x['kind'] == 'purchase'), default=anchor['event_ms'] - window)
            row[f'prior_decision_count_{suffix}'] = len(prior_decisions)
            row[f'prior_positive_rate_{suffix}'] = (sum(x['target'] for x in prior_decisions) + 1.0) / (len(prior_decisions) + 2.0)
        rows.append(row)
    train = [x for x in rows if x['split'] == 'train']; assert train
    exposure_names = tuple(f"open_purchase_amount_{SUFFIX[window]}" for window in policy['window_ms'])
    entity_stats = {}
    for row in train:
        stats = entity_stats.setdefault(row['entity_id'], [0, 0, [0.0 for _ in exposure_names], row['anchor_ms']])
        stats[0] += 1; stats[1] += row['target']; stats[3] = min(stats[3], row['anchor_ms'])
        for index, name in enumerate(exposure_names): stats[2][index] += row[name]
    fold_stats = [[0, 0, [0.0 for _ in exposure_names]] for _ in range(3)]; folds = {}
    for entity_id, (anchor_count, positive_count, exposure_totals, first_anchor_ms) in sorted(entity_stats.items(), key=lambda item: (-item[1][0], -item[1][1], tuple(-value for value in item[1][2]), item[1][3], item[0])):
        fold = min(range(3), key=lambda number: (fold_stats[number][0], fold_stats[number][1], tuple(fold_stats[number][2]), number))
        folds[entity_id] = fold; fold_stats[fold][0] += anchor_count; fold_stats[fold][1] += positive_count
        for index, value in enumerate(exposure_totals): fold_stats[fold][2][index] += value
    assert all(anchor_count for anchor_count, _, _ in fold_stats)
    for row in rows: row['calibration_fold'] = folds[row['entity_id']] if row['split'] == 'train' else None
    means = {name: accurate_sum(x[name] for x in train) / len(train) for name in raw}
    scales = {name: math.sqrt(accurate_sum((x[name] - means[name]) ** 2 for x in train) / len(train)) for name in raw}
    scales = {name: value or 1.0 for name, value in scales.items()}
    robust_medians = {name: median([x[name] for x in train]) for name in raw}
    robust_mads = {name: median([abs(x[name] - robust_medians[name]) for x in train]) or 1.0 for name in raw}
    for row in rows:
        cohort = train if row['split'] == 'test' else [candidate for candidate in train if candidate['calibration_fold'] != row['calibration_fold']]
        if not cohort: raise ValueError('no calibration cohort')
        cohort_means = {name: accurate_sum(candidate[name] for candidate in cohort) / len(cohort) for name in raw}
        cohort_scales = {name: math.sqrt(accurate_sum((candidate[name] - cohort_means[name]) ** 2 for candidate in cohort) / len(cohort)) for name in raw}
        cohort_scales = {name: value or 1.0 for name, value in cohort_scales.items()}
        cohort_medians = {name: median([candidate[name] for candidate in cohort]) for name in raw}
        cohort_mads = {name: median([abs(candidate[name] - cohort_medians[name]) for candidate in cohort]) or 1.0 for name in raw}
        for name in raw: row['z_' + name] = (row[name] - cohort_means[name]) / cohort_scales[name]
        for name in raw: row['r_' + name] = (row[name] - cohort_medians[name]) / cohort_mads[name]
    return rows, {'schema_version': 1, 'input_rows': len(events), 'live_rows': len(values), 'anchors': len(rows), 'train_anchors': len(train), 'feature_order': list(raw), 'means': means, 'scales': scales, 'robust_medians': robust_medians, 'robust_mads': robust_mads}

def drop():
    user = pwd.getpwnam('runner'); os.setgid(user.pw_gid); os.setuid(user.pw_uid)

def path(name):
    value = OUT / name
    assert value.exists() and not value.is_symlink() and value.is_file() and value.resolve().parent == OUT.resolve()
    return value

def execute(events, policy, controls=None, preserve_checkpoint=False):
    (DATA / 'events.jsonl').write_text(''.join(json.dumps(x) + '\n' for x in events), encoding='utf-8')
    (DATA / 'policy.json').write_text(json.dumps(policy), encoding='utf-8')
    for name in ARTIFACTS:
        candidate = OUT / name
        if os.path.lexists(candidate): candidate.unlink()
    if not preserve_checkpoint and os.path.lexists(CHECKPOINT): CHECKPOINT.unlink()
    os.chmod('/tests', 0o700)
    environment = {'PATH': os.environ['PATH']}
    if controls: environment.update(controls)
    return subprocess.run([sys.executable, '/app/feature_bundle.py'], cwd='/app', env=environment, preexec_fn=drop, capture_output=True, text=True, timeout=60)

def execute_raw(events_text, policy_text):
    """Run arbitrary serialized inputs so malformed JSON is rejected by the candidate program."""
    (DATA / 'events.jsonl').write_text(events_text, encoding='utf-8')
    (DATA / 'policy.json').write_text(policy_text, encoding='utf-8')
    for name in ARTIFACTS:
        candidate = OUT / name
        if os.path.lexists(candidate): candidate.unlink()
    if os.path.lexists(CHECKPOINT): CHECKPOINT.unlink()
    os.chmod('/tests', 0o700)
    return subprocess.run([sys.executable, '/app/feature_bundle.py'], cwd='/app', env={'PATH': os.environ['PATH']}, preexec_fn=drop, capture_output=True, text=True, timeout=60)

def run(events=None, policy=None):
    events = base_events() if events is None else events
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']} if policy is None else policy
    return execute(events, policy), oracle(events, policy)

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, f'duplicate output key: {key}'
        result[key] = value
    return result

def output_text(name):
    descriptor = os.open(path(name), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, encoding='utf-8') as stream:
        return stream.read()

def assert_outputs(want_rows, want_manifest):
    rows = [json.loads(line, object_pairs_hook=unique_object) for line in output_text('feature_bundle.jsonl').splitlines()]
    manifest = json.loads(output_text('feature_manifest.json'), object_pairs_hook=unique_object)
    assert len(rows) == len(want_rows) and set(manifest) == set(want_manifest)
    for actual, expected in zip(rows, want_rows):
        assert set(actual) == set(expected)
        for key, value in expected.items():
            if isinstance(value, float):
                assert type(actual[key]) in (int, float), f'{key} must be numeric, not boolean'
                assert math.isfinite(actual[key]) and abs(actual[key] - value) <= 1e-9, (
                    f'{expected["anchor_id"]}.{key}: expected {value}, got {actual[key]}'
                )
            else:
                assert type(actual[key]) is type(value) and actual[key] == value
    raw = tuple(want_manifest['feature_order'])
    assert type(manifest['schema_version']) is int and manifest['schema_version'] == 1 and manifest['feature_order'] == list(raw)
    for key in ('input_rows', 'live_rows', 'anchors', 'train_anchors'):
        assert type(manifest[key]) is int and manifest[key] == want_manifest[key]
    for section in ('means', 'scales', 'robust_medians', 'robust_mads'):
        assert set(manifest[section]) == set(raw)
        for name in raw:
            assert type(manifest[section][name]) in (int, float)
            assert math.isfinite(manifest[section][name]) and abs(manifest[section][name] - want_manifest[section][name]) <= 1e-9

def semantic_invalid_stream(case):
    """Append schema-valid records so the failure can lie beyond a saved prefix."""
    events = base_events()
    if case == 'final-revision-tie':
        events.append(event('n-p1', 1, 'north', 1200, 40, 'purchase', 6.0))
    elif case == 'as-of-tie-eclipsed-later':
        events.extend([
            event('n-p1', 1, 'north', 1200, 40, 'purchase', 5.0, available_ms=1201),
            event('n-p1', 2, 'north', 1200, 41, 'refund', 5.0, available_ms=1400),
        ])
    else:
        assert case in ('no-train-anchors', 'insufficient-occupied-folds')
        # Retain the held-out anchor; remove all train anchors or just the
        # south entity, leaving two occupied folds despite three train rows.
        removed = {'n-d1', 'n-d2', 'r-d1', 's-d1'} if case == 'no-train-anchors' else {'s-d1'}
        events.extend({**item, 'revision': 2, 'kind': 'click', 'target': None}
                      for item in base_events() if item['record_id'] in removed)
    return events

SEMANTIC_INVALID_CASES = (
    'final-revision-tie', 'as-of-tie-eclipsed-later',
    'no-train-anchors', 'insufficient-occupied-folds',
)

def assert_semantic_rejection(result):
    assert result.returncode not in (0, 75), (
        f'invalid complete stream was accepted with status {result.returncode}: {result.stderr}'
    )
    assert all(not os.path.lexists(OUT / name) for name in ARTIFACTS)

@pytest.mark.parametrize('case', SEMANTIC_INVALID_CASES)
@pytest.mark.parametrize('cut', [1, 11])
def test_semantic_invalid_stream_cannot_create_checkpoint(case, cut):
    """An interrupt validates the whole stream, including semantic defects after N."""
    events = semantic_invalid_stream(case)
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    result = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': str(cut)})
    assert_semantic_rejection(result)
    assert not os.path.lexists(CHECKPOINT), 'invalid stream created an accepted prefix checkpoint'

@pytest.mark.parametrize('case', SEMANTIC_INVALID_CASES)
@pytest.mark.parametrize('chain', [(4,), (4, 8)], ids=['one-prefix', 'chained-prefix'])
@pytest.mark.parametrize('interrupt_again', [False, True], ids=['resume', 'resume-interrupt'])
def test_semantic_invalid_resume_is_rejected(case, chain, interrupt_again):
    """Reject semantic defects in prefix-plus-suffix before accepting a longer checkpoint."""
    events = base_events()
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    consumed = 0
    for cut in chain:
        controls = {'INTERRUPT_AFTER_RECORD': str(cut)}
        if consumed: controls['RESUME'] = '1'
        stopped = execute(events[consumed:], policy, controls=controls, preserve_checkpoint=bool(consumed))
        assert stopped.returncode == 75, stopped.stderr
        consumed = cut
    previous = json.loads(path('feature_checkpoint.json').read_text(encoding='utf-8'))
    assert previous['consumed_rows'] == consumed and previous['consumed_events'] == events[:consumed]
    controls = {'RESUME': '1'}
    if interrupt_again: controls['INTERRUPT_AFTER_RECORD'] = str(consumed + 1)
    rejected = execute(semantic_invalid_stream(case)[consumed:], policy,
                       controls=controls, preserve_checkpoint=True)
    assert_semantic_rejection(rejected)

@pytest.mark.parametrize('cut', [1, 4, 7, 11])
def test_interrupted_then_resumed_stream_matches_uninterrupted_artifacts(cut):
    """A checkpoint must preserve an arbitrary physical prefix, including revisions later resolved from the suffix."""
    events, policy = base_events(), {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    want = oracle(events, policy)
    stopped = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': str(cut)})
    assert stopped.returncode == 75 and all(not (OUT / name).exists() for name in ARTIFACTS)
    checkpoint = json.loads(path('feature_checkpoint.json').read_text(encoding='utf-8'))
    assert type(checkpoint['schema_version']) is int
    assert checkpoint == {
        'schema_version': 1,
        'policy_sha256': hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest(),
        'consumed_rows': cut,
        'consumed_events': events[:cut],
    }
    resumed = execute(events[cut:], policy, controls={'RESUME': '1'}, preserve_checkpoint=True)
    assert resumed.returncode == 0, resumed.stderr; assert_outputs(*want); assert not CHECKPOINT.exists()

def test_resumed_stream_can_be_interrupted_again_before_completion():
    """A resume may extend the validated physical prefix, then a later resume reconstructs the same stream."""
    events, policy = base_events(), {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    want = oracle(events, policy)
    initial = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': '4'})
    assert initial.returncode == 75
    extended = execute(events[4:], policy, controls={'RESUME': '1', 'INTERRUPT_AFTER_RECORD': '8'}, preserve_checkpoint=True)
    assert extended.returncode == 75 and all(not (OUT / name).exists() for name in ARTIFACTS)
    checkpoint = json.loads(path('feature_checkpoint.json').read_text(encoding='utf-8'))
    assert checkpoint['consumed_rows'] == 8 and checkpoint['consumed_events'] == events[:8]
    completed = execute(events[8:], policy, controls={'RESUME': '1'}, preserve_checkpoint=True)
    assert completed.returncode == 0, completed.stderr; assert_outputs(*want); assert not CHECKPOINT.exists()

@pytest.mark.parametrize('count', [3, 4], ids=['rewind', 'unchanged-prefix'])
def test_resumed_interrupt_cannot_rewind_the_checkpoint_prefix(count):
    """A chained interruption must advance; invalid attempts cannot report a checkpoint or final output."""
    events, policy = base_events(), {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    stopped = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': '4'})
    assert stopped.returncode == 75
    rewound = execute(events[4:], policy, controls={'RESUME': '1', 'INTERRUPT_AFTER_RECORD': str(count)}, preserve_checkpoint=True)
    assert rewound.returncode not in (0, 75), 'invalid resumption must not report successful checkpointing'
    assert all(not os.path.lexists(OUT / name) for name in ARTIFACTS)
    # The contract does not require retaining a rejected checkpoint.

def test_resume_rejects_policy_mismatch_without_final_artifacts():
    """A checkpoint cannot be replayed against a policy different from the one that created it."""
    events = base_events(); policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    stopped = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': '5'}); assert stopped.returncode == 75
    changed = {'window_ms': [300000, 3600000], 'holdout_entities': ['rivulet']}
    resumed = execute(events[5:], changed, controls={'RESUME': '1'}, preserve_checkpoint=True)
    assert resumed.returncode not in (0, 75) and all(not (OUT / name).exists() for name in ARTIFACTS)

def test_malformed_checkpoint_is_rejected_without_final_artifacts():
    """Resume validates checkpoint schema and cannot treat a partial/stub state file as a prefix."""
    events = base_events(); policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    stopped = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': '5'}); assert stopped.returncode == 75
    CHECKPOINT.write_text('{"schema_version":1}', encoding='utf-8')
    resumed = execute(events[5:], policy, controls={'RESUME': '1'}, preserve_checkpoint=True)
    assert resumed.returncode not in (0, 75) and all(not (OUT / name).exists() for name in ARTIFACTS)

@pytest.mark.parametrize('version', [True, 1.0, '1', 0, 2, None],
                         ids=['boolean', 'float', 'string', 'below', 'above', 'null'])
@pytest.mark.parametrize('interrupt_again', [False, True], ids=['resume', 'resume-interrupt'])
def test_checkpoint_version_requires_exact_integer_one(version, interrupt_again):
    """A numerically equal noninteger or unsupported version is malformed on either resume path."""
    events = base_events(); policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    stopped = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': '5'})
    assert stopped.returncode == 75, stopped.stderr
    checkpoint = json.loads(path('feature_checkpoint.json').read_text(encoding='utf-8'))
    checkpoint['schema_version'] = version
    CHECKPOINT.write_text(json.dumps(checkpoint), encoding='utf-8')
    controls = {'RESUME': '1'}
    if interrupt_again: controls['INTERRUPT_AFTER_RECORD'] = '8'
    rejected = execute(events[5:], policy, controls=controls, preserve_checkpoint=True)
    assert rejected.returncode not in (0, 75), (
        f'malformed checkpoint version {version!r} was accepted with status {rejected.returncode}'
    )
    assert all(not os.path.lexists(OUT / name) for name in ARTIFACTS)

@pytest.mark.parametrize('controls', [
    {'INTERRUPT_AFTER_RECORD': '0'},
    {'INTERRUPT_AFTER_RECORD': '12'},
    {'INTERRUPT_AFTER_RECORD': 'not-a-number'},
    {'RESUME': 'not-one'},
])
def test_invalid_execution_controls_fail_without_final_artifacts(controls):
    """Only valid stop or resume modes may affect the recoverable processing lifecycle."""
    result = execute(base_events(), {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}, controls=controls)
    assert result.returncode not in (0, 75), 'invalid controls must not be accepted as a checkpoint'
    assert all(not (OUT / name).exists() for name in ARTIFACTS) and not CHECKPOINT.exists()

def test_default_bundle_and_manifest_match_contract():
    """Default reconciled events produce the complete canonical feature bundle and manifest."""
    result, want = run(); assert result.returncode == 0, result.stderr; assert_outputs(*want)

def test_three_window_profile_derives_a_dynamic_feature_schema():
    """A valid 15-minute policy window expands rows, scores, and manifest maps without hard-coded two-window names."""
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': ['hazel']}
    result, want = run(policy=policy); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    assert want[1]['feature_order'] == list(raw_names(policy['window_ms']))
    assert all('click_count_15m' in row and 'z_click_count_15m' in row and 'r_click_count_15m' in row for row in want[0])

def test_shuffled_physical_lines_do_not_change_event_time_bundle():
    """Physical JSONL ordering cannot alter canonical event-time features."""
    events = base_events()
    result, want = run(events); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    original = ([json.loads(line) for line in path(ARTIFACTS[0]).read_text(encoding='utf-8').splitlines()],
                json.loads(path(ARTIFACTS[1]).read_text(encoding='utf-8')))
    for permutation in (list(reversed(events)), events[5:] + events[:5], events[::2] + events[1::2]):
        result = execute(permutation, {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']})
        assert result.returncode == 0, result.stderr
        assert_outputs(*original)
        assert_outputs(*want)

@pytest.mark.parametrize('sign', [1.0, -1.0], ids=['positive-residual', 'negative-residual'])
@pytest.mark.parametrize('windows', [[300000, 3600000], [300000, 900000, 3600000]], ids=['two-windows', 'three-windows'])
def test_cancellation_sensitive_shuffles_preserve_numeric_truth(sign, windows):
    """Nested cancellation defeats even compensated sum; permutations must retain the exact residual."""
    # The two large pairs cancel exactly as finite binary rationals. In the
    # lossy ordering, the tiny term is lost from the compensated error total,
    # not just the primary accumulator (including CPython's improved sum).
    amounts = [sign * value for value in (2.0 ** 53, 1.0, 1e100, -1e100, -2.0 ** 53)]
    expected_net = sign
    assert sum((Fraction(value) for value in amounts), Fraction()) == Fraction(expected_net)
    groups = []
    for index, amount in enumerate(amounts):
        group = [event(f'cancel-{index}', 1, 'north', 1000 + index * 2, 20 + index * 2, 'purchase', amount)]
        if amount > 0:
            # Settle each balance before the next purchase in canonical event
            # time: only the small purchase-net residual reaches calibration.
            group.append(event(f'settle-{index}', 1, 'north', 1001 + index * 2, 21 + index * 2, 'refund', amount))
        groups.append(group)
    anchors = [event(f'{entity}-anchor', 1, entity, 2000 + index, 30 + index, 'decision', target=0)
               for index, entity in enumerate(('north', 'south', 'east', 'held'))]
    policy = {'window_ms': windows, 'holdout_entities': ['held']}
    orders = ((2, 3, 0, 4, 1), (0, 1, 2, 3, 4), (4, 3, 2, 1, 0), (1, 0, 2, 3, 4))
    events = [item for index in orders[0] for item in groups[index]] + anchors
    # Derive reference truth once, before any submitted child can access inputs.
    want = oracle(events, policy)
    for window in windows:
        name = f'purchase_net_{SUFFIX[window]}'
        assert want[0][0][name] == expected_net
        assert want[0][0][f'open_purchase_amount_{SUFFIX[window]}'] == 0.0
        assert want[1]['means'][name] == expected_net / 3.0
    original = None
    for index, order in enumerate(orders):
        permutation = [item for position in order for item in groups[position]] + (anchors if index == 0 else list(reversed(anchors)))
        result = execute(permutation, policy)
        assert result.returncode == 0, result.stderr
        if original is not None: assert_outputs(*original)
        assert_outputs(*want)
        if original is None:
            original = ([json.loads(line) for line in path(ARTIFACTS[0]).read_text(encoding='utf-8').splitlines()],
                        json.loads(path(ARTIFACTS[1]).read_text(encoding='utf-8')))

@pytest.mark.parametrize('sign', [1.0, -1.0], ids=['positive-residual', 'negative-residual'])
@pytest.mark.parametrize('resume', [False, True], ids=['uninterrupted', 'resumed'])
def test_finite_purchase_sum_survives_intermediate_overflow(sign, resume):
    """Finite cancelling amounts must retain their small result through permutation and resume."""
    amounts = [sign * value for value in (1e308, 1e308, -1e308, -1e308, 1.0)]
    assert sum((Fraction(value) for value in amounts), Fraction()) == Fraction(sign)
    groups = []
    for index, amount in enumerate(amounts):
        group = [event(f'large-{index}', 1, 'north', 1000 + 2 * index, 20 + 2 * index, 'purchase', amount)]
        if amount > 0:
            group.append(event(f'settle-large-{index}', 1, 'north', 1001 + 2 * index, 21 + 2 * index, 'refund', amount))
        groups.append(group)
    anchors = [event(f'{entity}-anchor', 1, entity, 2000 + index, 40 + index, 'decision', target=0)
               for index, entity in enumerate(('north', 'south', 'east', 'held'))]
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': ['held']}
    orders = ((0, 2, 1, 3, 4), (0, 1, 2, 3, 4), (4, 3, 2, 1, 0))
    original_events = [item for index in orders[0] for item in groups[index]] + anchors
    want = oracle(original_events, policy)
    for suffix in SUFFIX.values():
        name = f'purchase_net_{suffix}'
        assert want[0][0][name] == sign
        assert want[0][0][f'open_purchase_amount_{suffix}'] == 0.0
        assert want[1]['means'][name] == sign / 3.0
    result = execute(original_events, policy)
    assert result.returncode == 0, result.stderr
    assert_outputs(*want)
    original = ([json.loads(line) for line in path(ARTIFACTS[0]).read_text(encoding='utf-8').splitlines()],
                json.loads(path(ARTIFACTS[1]).read_text(encoding='utf-8')))
    for order in orders:
        events = [item for index in order for item in groups[index]] + list(reversed(anchors))
        if resume:
            stopped = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': '3'})
            assert stopped.returncode == 75, stopped.stderr
            assert not any((OUT / name).exists() for name in ARTIFACTS)
            result = execute(events[3:], policy, controls={'RESUME': '1'}, preserve_checkpoint=True)
            assert not CHECKPOINT.exists()
        else:
            result = execute(events, policy)
        assert result.returncode == 0, result.stderr
        assert_outputs(*original)
        assert_outputs(*want)

def test_later_revision_replaces_the_prior_record():
    """A higher revision changes the live event used for a decision's history."""
    events = base_events() + [event('n-p1', 2, 'north', 1200, 30, 'purchase', 11.0)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_revised_decision_replaces_the_anchor_itself():
    """Reconciliation applies to decision anchors as well as to their history records."""
    events = base_events() + [event('n-d1', 2, 'north', 1450, 34, 'decision', target=0)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_revised_record_can_change_the_feature_kind():
    """A correction replaces the entire live record, including its history kind and amount."""
    events = base_events() + [event('n-p1', 2, 'north', 1200, 35, 'refund', 7.0)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_revision_replaces_entity_as_well_as_feature_fields():
    """A correction is a complete replacement, so its prior entity cannot retain the old event."""
    events = base_events() + [event('n-p1', 2, 'south', 1200, 35, 'purchase', 7.0)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_revision_can_turn_a_decision_into_history():
    """A later non-decision revision removes an anchor and may become ordinary history."""
    events = base_events() + [event('n-d1', 2, 'north', 1300, 35, 'click')]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_revised_history_can_move_across_an_anchor_boundary():
    """A corrected event timestamp is reconciled before event-time history is selected."""
    events = base_events() + [event('n-p1', 2, 'north', 2000, 36, 'purchase', 8.0)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

@pytest.mark.parametrize('case', range(8))
def test_as_of_complete_correction_changes_history_between_anchors(case):
    """Each anchor chooses its own available revision, even when a correction moves an event to another entity and kind."""
    base = 10_000_000 + case * 100_000
    early, correction_available, later = base + 10_000, base + 10_001 + case, base + 20_000
    north, south, east = f'north-{case}', f'south-{case}', f'east-{case}'
    events = [
        event('switch', 1, north, early - 700 - case, 1, 'purchase', 10.0 + case),
        event('switch', 2, south, early - 600 - case, 2, 'refund', 999.0, available_ms=correction_available),
        event('prior-switch', 1, north, early - 800 - case, 3, 'decision', target=1),
        event('prior-switch', 2, south, early - 500 - case, 4, 'refund', 123.0, available_ms=correction_available),
        event('tie', 1, north, early, 5, 'click'),
        event('north-early', 1, north, early, 6, 'decision', target=case % 2),
        event('north-later', 1, north, later, 7, 'decision', target=(case + 1) % 2),
        event('south-anchor', 1, south, later + 100, 8, 'decision', target=case % 2),
        event('east-anchor', 1, east, later + 200, 9, 'decision', target=(case + 1) % 2),
    ]
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': []}
    result, want = run(events, policy); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    rows = {row['anchor_id']: row for row in want[0]}
    assert rows['north-early']['purchase_net_5m'] == 10.0 + case
    assert rows['north-early']['refund_count_5m'] == 0 and rows['north-early']['click_count_5m'] == 0
    assert rows['north-early']['prior_decision_count_5m'] == 1 and rows['north-early']['prior_positive_rate_5m'] == 2.0 / 3.0
    assert rows['north-later']['purchase_net_5m'] == 0.0 and rows['north-later']['refund_count_5m'] == 0
    assert rows['south-anchor']['purchase_net_5m'] == 0.0 and rows['south-anchor']['refund_count_5m'] == 2

@pytest.mark.parametrize('case', range(8))
def test_open_purchase_ledger_uses_fifo_canonical_activity_order(case):
    """Partial refunds must consume the oldest outstanding purchase in event/ingest/ID order, not merely net totals."""
    anchor = 20_000_000 + case * 100_000
    north, south, east = f'ledger-north-{case}', f'ledger-south-{case}', f'ledger-east-{case}'
    refund_before_second_purchase = case % 2 == 0
    refund_time, refund_seq = (anchor - 600, 4) if refund_before_second_purchase else (anchor - 300, 6)
    second_time, second_seq = (anchor - 600, 5) if refund_before_second_purchase else (anchor - 600, 4)
    events = [
        event('first-purchase', 1, north, anchor - 900, 1, 'purchase', 5.0 + case),
        event('refund', 1, north, refund_time, refund_seq, 'refund', 6.0 + case),
        event('second-purchase', 1, north, second_time, second_seq, 'purchase', 7.0 + case),
        event('north-anchor', 1, north, anchor, 7, 'decision', target=case % 2),
        event('south-anchor', 1, south, anchor + 100, 8, 'decision', target=(case + 1) % 2),
        event('east-anchor', 1, east, anchor + 200, 9, 'decision', target=case % 2),
    ]
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': []}
    result, want = run(events, policy); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    row = next(item for item in want[0] if item['anchor_id'] == 'north-anchor')
    assert row['open_purchase_amount_5m'] == (7.0 + case if refund_before_second_purchase else 6.0 + case)
    assert row['oldest_open_purchase_age_ms_5m'] == 600

@pytest.mark.parametrize('window', [300000, 900000, 3600000], ids=['5m', '15m', '1h'])
@pytest.mark.parametrize('offset', [-1, 0, 1], ids=['before-lower', 'at-lower', 'after-lower'])
@pytest.mark.parametrize('refund', [0.0, 4.0], ids=['unsettled', 'partially-settled'])
@pytest.mark.parametrize('resume', [False, True], ids=['uninterrupted', 'resumed'])
def test_open_purchase_projection_includes_lower_boundary(window, offset, refund, resume):
    """Project FIFO balances at lower-1/lower/lower+1, including partial settlement and resume."""
    anchor = window + 1000
    events = [
        event('boundary-purchase', 1, 'north', 1000 + offset, 1, 'purchase', 9.0),
        event('younger-purchase', 1, 'north', anchor - 20, 2, 'purchase', 5.0),
        event('partial-refund', 1, 'north', anchor - 10, 3, 'refund', refund),
        event('north-anchor', 1, 'north', anchor, 4, 'decision', target=1),
        event('south-purchase', 1, 'south', anchor - 20, 5, 'purchase', 2.0),
        event('south-anchor', 1, 'south', anchor + 1, 6, 'decision', target=1),
        event('east-purchase', 1, 'east', anchor - 20, 7, 'purchase', 7.0),
        event('east-anchor', 1, 'east', anchor + 2, 8, 'decision', target=1),
    ]
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': []}
    if resume:
        events.reverse()
        stopped = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': '3'})
        assert stopped.returncode == 75, stopped.stderr
        result = execute(events[3:], policy, controls={'RESUME': '1'}, preserve_checkpoint=True)
    else:
        result = execute(events, policy)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in output_text('feature_bundle.jsonl').splitlines()]
    row = next(item for item in rows if item['anchor_id'] == 'north-anchor')
    suffix = SUFFIX[window]
    # FIFO first reduces the older lot even when that lot is outside W. Its
    # remaining balance is retained at equality, and excluded only before W.
    expected_open = 5.0 + (9.0 - refund if offset >= 0 else 0.0)
    expected_age = window - offset if offset >= 0 else 20
    assert row[f'open_purchase_amount_{suffix}'] == expected_open, (
        'FIFO projection must include the originating purchase exactly at anchor_ms-W'
    )
    assert row[f'oldest_open_purchase_age_ms_{suffix}'] == expected_age
    assert row[f'purchase_net_{suffix}'] == (14.0 if offset >= 0 else 5.0)
    # The other two entities have exposures 2 and 7 and occupy the other folds.
    # Their mean/median is 4.5 and population scale/MAD is 2.5.
    for prefix in ('z_', 'r_'):
        assert abs(row[f'{prefix}open_purchase_amount_{suffix}'] - (expected_open - 4.5) / 2.5) <= 1e-9
    manifest = json.loads(output_text('feature_manifest.json'))
    assert abs(manifest['means'][f'open_purchase_amount_{suffix}'] - (expected_open + 9.0) / 3.0) <= 1e-9
    assert_outputs(*oracle(events, policy))


@pytest.mark.parametrize('refund_first', [True, False], ids=['refund-first', 'purchase-first'])
def test_fifo_activity_ties_use_record_id(refund_first):
    """At equal event time and ingest sequence, record IDs decide whether a refund can settle a purchase."""
    purchase_id, refund_id = ('z-purchase', 'a-refund') if refund_first else ('a-purchase', 'z-refund')
    events = [
        event(purchase_id, 1, 'north', 500, 7, 'purchase', 9.0),
        event(refund_id, 1, 'north', 500, 7, 'refund', 4.0),
        event('north-anchor', 1, 'north', 1000, 8, 'decision', target=1),
        event('south-anchor', 1, 'south', 1100, 9, 'decision', target=1),
        event('east-anchor', 1, 'east', 1200, 10, 'decision', target=1),
    ]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': []}
    expected = 9.0 if refund_first else 5.0
    # Both physical orders must yield the same canonical settlement result.
    for physical in (events, list(reversed(events))):
        result = execute(physical, policy)
        assert result.returncode == 0, result.stderr
        rows = [json.loads(line) for line in output_text('feature_bundle.jsonl').splitlines()]
        row = next(item for item in rows if item['anchor_id'] == 'north-anchor')
        assert row['open_purchase_amount_5m'] == expected, 'FIFO tie must use record_id after event_ms and ingest_seq'
        assert row['oldest_open_purchase_age_ms_5m'] == 500
        assert row['purchase_net_5m'] == 9.0 and row['refund_count_5m'] == 1
        assert_outputs(*oracle(physical, policy))


@pytest.mark.parametrize('available_offset', [-1, 0, 1], ids=['before-anchor', 'at-anchor', 'after-anchor'])
@pytest.mark.parametrize('resume', [False, True], ids=['uninterrupted', 'resumed'])
def test_fifo_refund_availability_at_anchor_is_inclusive(available_offset, resume):
    """Ledger settlement includes a refund available exactly at the anchor, while excluding one available later."""
    events = [
        event('purchase', 1, 'north', 900, 1, 'purchase', 9.0),
        event('refund', 1, 'north', 950, 2, 'refund', 4.0, available_ms=1000 + available_offset),
        event('north-anchor', 1, 'north', 1000, 3, 'decision', target=1),
        event('south-anchor', 1, 'south', 1100, 4, 'decision', target=1),
        event('east-anchor', 1, 'east', 1200, 5, 'decision', target=1),
    ]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': []}
    if resume:
        stopped = execute(events, policy, controls={'INTERRUPT_AFTER_RECORD': '2'})
        assert stopped.returncode == 75, stopped.stderr
        result = execute(events[2:], policy, controls={'RESUME': '1'}, preserve_checkpoint=True)
    else:
        result = execute(events, policy)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in output_text('feature_bundle.jsonl').splitlines()]
    row = next(item for item in rows if item['anchor_id'] == 'north-anchor')
    assert row['open_purchase_amount_5m'] == (5.0 if available_offset <= 0 else 9.0), (
        'FIFO must use every selected activity available at anchor_ms, including equality'
    )
    assert row['refund_count_5m'] == (1 if available_offset <= 0 else 0)
    assert row['oldest_open_purchase_age_ms_5m'] == 100
    assert_outputs(*oracle(events, policy))


@pytest.mark.parametrize('case', range(8))
def test_as_of_fifo_settlement_flows_into_fold_disjoint_normalization(case):
    """A late correction changes the ledger between anchors, and the affected rows must use their fold-excluded cohorts."""
    early = 30_000_000 + case * 100_000
    later, available = early + 10_000, early + 1
    north, south, east, west, held = (f'{label}-{case}' for label in ('north', 'south', 'east', 'west', 'held'))
    events = [
        event('revised-purchase', 1, north, early - 900, 1, 'purchase', 5.0 + case),
        event('revised-purchase', 2, south, early - 800, 2, 'refund', 999.0, available_ms=available),
        event('second-purchase', 1, north, early - 500, 3, 'purchase', 7.0 + case),
        event('north-refund', 1, north, early - 500, 4, 'refund', 6.0 + case),
        event('north-early', 1, north, early, 5, 'decision', target=case % 2),
        event('north-later', 1, north, later, 6, 'decision', target=(case + 1) % 2),
        event('south-anchor', 1, south, later + 100, 7, 'decision', target=case % 2),
        event('east-anchor', 1, east, later + 200, 8, 'decision', target=(case + 1) % 2),
        event('west-anchor', 1, west, later + 300, 9, 'decision', target=case % 2),
        event('held-anchor', 1, held, later + 400, 10, 'decision', target=(case + 1) % 2),
    ]
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': [held]}
    result, want = run(events, policy); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    rows, manifest = want; by_anchor = {row['anchor_id']: row for row in rows}
    early_row, later_row, south_row = by_anchor['north-early'], by_anchor['north-later'], by_anchor['south-anchor']
    assert early_row['open_purchase_amount_5m'] == 6.0 + case and early_row['oldest_open_purchase_age_ms_5m'] == 500
    assert later_row['open_purchase_amount_5m'] == 1.0 and later_row['oldest_open_purchase_age_ms_5m'] == 10500
    assert south_row['open_purchase_amount_5m'] == 0.0 and south_row['oldest_open_purchase_age_ms_5m'] == 300000
    global_z = (early_row['open_purchase_amount_5m'] - manifest['means']['open_purchase_amount_5m']) / manifest['scales']['open_purchase_amount_5m']
    assert early_row['z_open_purchase_amount_5m'] != global_z

@pytest.mark.parametrize('case', range(8))
def test_fifo_ledger_carries_state_across_window_boundaries(case):
    """A refund inside a short window first settles older pre-window state before W-origin balances are projected."""
    early = 35_000_000 + case * 100_000
    later, available = early + 10_000, early + 1
    north, south, east, west = (f'{label}-carry-{case}' for label in ('north', 'south', 'east', 'west'))
    events = [
        event('carried-state', 1, north, early - 300001, 1, 'purchase', 10.0 + case),
        event('carried-state', 2, south, early - 300000, 2, 'refund', 999.0, available_ms=available),
        event('window-purchase', 1, north, early - 100000, 3, 'purchase', 5.0 + case),
        event('window-refund', 1, north, early - 50000, 4, 'refund', 7.0 + case),
        event('north-early', 1, north, early, 5, 'decision', target=case % 2),
        event('north-later', 1, north, later, 6, 'decision', target=(case + 1) % 2),
        event('south-anchor', 1, south, later + 100, 7, 'decision', target=case % 2),
        event('east-anchor', 1, east, later + 200, 8, 'decision', target=(case + 1) % 2),
        event('west-anchor', 1, west, later + 300, 9, 'decision', target=case % 2),
    ]
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': []}
    result, want = run(events, policy); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    rows, manifest = want; by_anchor = {row['anchor_id']: row for row in rows}
    early_row, later_row, south_row = by_anchor['north-early'], by_anchor['north-later'], by_anchor['south-anchor']
    assert early_row['open_purchase_amount_5m'] == 5.0 + case
    assert early_row['oldest_open_purchase_age_ms_5m'] == 100000
    assert early_row['open_purchase_amount_15m'] == 8.0 + case
    assert early_row['oldest_open_purchase_age_ms_15m'] == 300001
    assert later_row['open_purchase_amount_5m'] == 0.0 and later_row['oldest_open_purchase_age_ms_5m'] == 300000
    assert south_row['open_purchase_amount_5m'] == 0.0
    global_z = (early_row['open_purchase_amount_5m'] - manifest['means']['open_purchase_amount_5m']) / manifest['scales']['open_purchase_amount_5m']
    assert early_row['z_open_purchase_amount_5m'] != global_z

@pytest.mark.parametrize('case', range(8))
def test_as_of_ledger_exposure_changes_calibration_fold_assignment(case):
    """Late revisions alter raw exposure before deterministic fold balancing, which in turn changes calibration cohorts."""
    base = 40_000_000 + case * 100_000
    amber, birch, cedar, dahlia, elm, fawn = (f'{label}-{case}' for label in ('amber', 'birch', 'cedar', 'dahlia', 'elm', 'fawn'))
    anchors = {amber: base + 1000, birch: base + 2000, cedar: base + 3000, dahlia: base + 4000, elm: base + 5000, fawn: base + 6000}
    events = [
        event('amber-purchase', 1, amber, anchors[amber] - 100, 1, 'purchase', 12.0 + case),
        event('birch-revision', 1, birch, anchors[birch] - 100, 2, 'purchase', 11.0 + case),
        event('birch-revision', 2, cedar, anchors[birch] - 90, 3, 'refund', 999.0, available_ms=anchors[birch] + 1),
        event('dahlia-purchase', 1, dahlia, anchors[dahlia] - 100, 4, 'purchase', 9.0 + case),
        event('elm-purchase', 1, elm, anchors[elm] - 100, 5, 'purchase', 8.0 + case),
        event('fawn-purchase', 1, fawn, anchors[fawn] - 100, 6, 'purchase', 1.0 + case),
    ] + [event(f'{entity}-anchor', 1, entity, anchor, 10 + index, 'decision', target=0) for index, (entity, anchor) in enumerate(anchors.items())]
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': []}
    result, want = run(events, policy); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    rows, manifest = want; by_entity = {row['entity_id']: row for row in rows}
    assert by_entity[birch]['open_purchase_amount_1h'] == 11.0 + case
    assert by_entity[cedar]['open_purchase_amount_1h'] == 0.0
    assert {entity: by_entity[entity]['calibration_fold'] for entity in anchors} == {amber: 0, birch: 1, cedar: 0, dahlia: 2, elm: 2, fawn: 1}
    global_z = (by_entity[birch]['open_purchase_amount_1h'] - manifest['means']['open_purchase_amount_1h']) / manifest['scales']['open_purchase_amount_1h']
    assert by_entity[birch]['z_open_purchase_amount_1h'] != global_z

@pytest.mark.parametrize('case', range(8))
def test_calibration_folds_balance_the_full_window_exposure_vector(case):
    """Equal 1-hour exposure must still be ordered and balanced by 5-minute then 15-minute ledger exposure."""
    base = 45_000_000 + case * 100_000
    layout = [('c0', 'far', 1_000_000), ('b0', 'middle', 600_000), ('a0', 'near', 100_000), ('c1', 'far', 1_000_000), ('b1', 'middle', 600_000), ('a1', 'near', 100_000)]
    events = []
    for index, (name, tier, age) in enumerate(layout):
        anchor = base + (index + 1) * 1000
        entity = f'{tier}-profile-{case}-{name}'
        events.extend([
            event(f'{name}-purchase', 1, entity, anchor - age, index * 2 + 1, 'purchase', 10.0 + case),
            event(f'{name}-anchor', 1, entity, anchor, index * 2 + 2, 'decision', target=0),
        ])
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': []}
    result, want = run(events, policy); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    rows = {row['entity_id']: row for row in want[0]}
    near = rows[f'near-profile-{case}-a0']; middle = rows[f'middle-profile-{case}-b0']; far = rows[f'far-profile-{case}-c0']
    assert (near['open_purchase_amount_5m'], near['open_purchase_amount_15m'], near['open_purchase_amount_1h']) == (10.0 + case, 10.0 + case, 10.0 + case)
    assert (middle['open_purchase_amount_5m'], middle['open_purchase_amount_15m'], middle['open_purchase_amount_1h']) == (0.0, 10.0 + case, 10.0 + case)
    assert (far['open_purchase_amount_5m'], far['open_purchase_amount_15m'], far['open_purchase_amount_1h']) == (0.0, 0.0, 10.0 + case)
    assert {entity: row['calibration_fold'] for entity, row in rows.items()} == {
        f'far-profile-{case}-c0': 0, f'middle-profile-{case}-b0': 2, f'near-profile-{case}-a0': 0,
        f'far-profile-{case}-c1': 1, f'middle-profile-{case}-b1': 2, f'near-profile-{case}-a1': 1,
    }

@pytest.mark.parametrize('case', range(8))
def test_as_of_revision_cascades_through_profile_folds_and_cohorts(case):
    """A correction crossing an anchor changes a ledger vector, singleton-fold membership, and a row's calibration cohort."""
    early = 55_000_000 + case * 100_000
    north, south, east, west = (f'{label}-cascade-{case}' for label in ('north', 'south', 'east', 'west'))
    events = [
        event('shape-shift', 1, north, early - 600000, 1, 'purchase', 13.0 + case),
        event('shape-shift', 2, south, early - 100, 2, 'refund', 999.0, available_ms=early + 1),
        event('north-tie', 1, north, early, 3, 'click'),
        event('east-purchase', 1, east, early + 3000 - 100, 4, 'purchase', 10.0 + case),
        event('west-purchase', 1, west, early + 4000 - 600000, 5, 'purchase', 10.0 + case),
        event('north-anchor', 1, north, early, 6, 'decision', target=0),
        event('south-anchor', 1, south, early + 2000, 7, 'decision', target=0),
        event('east-anchor', 1, east, early + 3000, 8, 'decision', target=0),
        event('west-anchor', 1, west, early + 4000, 9, 'decision', target=0),
    ]
    policy = {'window_ms': [300000, 900000, 3600000], 'holdout_entities': []}
    result, want = run(events, policy); assert result.returncode == 0, result.stderr; assert_outputs(*want)
    rows, manifest = want; by_entity = {row['entity_id']: row for row in rows}
    north_row, south_row = by_entity[north], by_entity[south]
    assert north_row['click_count_5m'] == 0
    assert (north_row['open_purchase_amount_5m'], north_row['open_purchase_amount_15m'], north_row['open_purchase_amount_1h']) == (0.0, 13.0 + case, 13.0 + case)
    assert south_row['refund_count_5m'] == 1 and south_row['open_purchase_amount_5m'] == 0.0
    assert {entity: row['calibration_fold'] for entity, row in by_entity.items()} == {north: 1, south: 2, east: 0, west: 2}
    assert manifest['means']['open_purchase_amount_5m'] == (10.0 + case) / 4.0
    assert manifest['means']['open_purchase_amount_15m'] == (33.0 + 3.0 * case) / 4.0
    if case == 0:
        assert abs(north_row['z_open_purchase_amount_15m'] - 19.0 / (10.0 * math.sqrt(2.0))) <= 1e-12
        assert north_row['r_open_purchase_amount_15m'] == 3.0

def test_half_open_windows_include_lower_bound_and_exclude_ties():
    """Window lower bounds contribute while events at the anchor timestamp do not."""
    events = base_events() + [event('n-low', 1, 'north', 1000, 31, 'click'), event('n-tie', 1, 'north', 3601000, 32, 'purchase', 99.0)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_future_events_never_contribute_to_earlier_anchor_features():
    """Same-entity activity after a decision is not available to that earlier decision."""
    events = base_events() + [event('n-future', 1, 'north', 1700, 37, 'purchase', 55.0)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_recency_uses_latest_selected_event_and_window_fallback():
    """Recency is event-time based, type-specific, and uses W only when relevant history is absent."""
    events = [
        event('north-left', 1, 'north', 300000, 1, 'click'),
        event('north-purchase', 1, 'north', 599900, 2, 'purchase', 4.0),
        event('north-refund', 1, 'north', 599950, 3, 'refund'),
        event('north-decision', 1, 'north', 600000, 4, 'decision', target=1),
        event('south-decision', 1, 'south', 610000, 5, 'decision', target=0),
        event('east-decision', 1, 'east', 620000, 6, 'decision', target=1),
        event('held-decision', 1, 'held', 630000, 7, 'decision', target=0),
    ]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['held']}
    result, want = run(events, policy); assert result.returncode == 0; assert_outputs(*want)
    north = next(row for row in want[0] if row['anchor_id'] == 'north-decision')
    south = next(row for row in want[0] if row['anchor_id'] == 'south-decision')
    assert north['click_count_5m'] == 1 and north['activity_recency_ms_5m'] == 50 and north['purchase_recency_ms_5m'] == 100
    assert south['activity_recency_ms_5m'] == 300000 and south['purchase_recency_ms_5m'] == 300000

def test_history_uses_versions_available_by_each_anchor():
    """Late corrections alter later rows while availability-at-anchor and event-time boundaries remain distinct."""
    events = base_events() + [
        event('n-p1', 2, 'north', 1200, 40, 'refund', 8.0, available_ms=1400),
        event('known-at-tie', 1, 'north', 1100, 41, 'click', available_ms=1300),
    ]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_equal_best_as_of_revision_is_rejected_before_artifacts():
    """A future unique revision cannot resolve a tie that was already ambiguous at an earlier anchor."""
    events = base_events() + [
        event('n-p1', 1, 'north', 1200, 40, 'purchase', 5.0, available_ms=1201),
        event('n-p1', 2, 'north', 1200, 41, 'refund', 5.0, available_ms=1400),
    ]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    assert_semantic_rejection(execute(events, policy))

def test_history_never_crosses_entity_or_uses_decisions():
    """Other entities and prior decisions never contribute activity features, even when temporally eligible."""
    events = base_events() + [event('h-huge', 1, 'hazel', 1200, 38, 'purchase', 99999.0), event('n-old-decision', 1, 'north', 1100, 39, 'decision', target=1)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_causal_label_prior_uses_as_of_decisions_but_not_activity_history():
    """A decision can be a label-prior observation even when its later correction becomes a non-activity record."""
    events = [
        event('north-prior', 1, 'north', 500000, 1, 'decision', target=1),
        event('north-prior', 2, 'north', 500000, 2, 'refund', 9.0, available_ms=600100),
        event('north-anchor', 1, 'north', 600000, 3, 'decision', target=0),
        event('south-anchor', 1, 'south', 610000, 4, 'decision', target=1),
        event('east-anchor', 1, 'east', 620000, 5, 'decision', target=0),
        event('held-anchor', 1, 'held', 630000, 6, 'decision', target=1),
    ]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['held']}
    result, want = run(events, policy); assert result.returncode == 0; assert_outputs(*want)
    north = next(row for row in want[0] if row['anchor_id'] == 'north-anchor')
    south = next(row for row in want[0] if row['anchor_id'] == 'south-anchor')
    assert north['prior_decision_count_5m'] == 1 and north['prior_positive_rate_5m'] == 2.0 / 3.0
    assert north['refund_count_5m'] == 0 and south['prior_decision_count_5m'] == 0 and south['prior_positive_rate_5m'] == 0.5

def test_canonical_anchor_order_uses_all_three_sort_fields():
    """Equal event times require ingest sequence and then record ID as deterministic tie-breakers."""
    events = [
        event('history', 1, 'order', 1000, 1, 'click'),
        event('z-last', 1, 'order', 2000, 5, 'decision', target=0),
        event('a-middle', 1, 'order', 2000, 5, 'decision', target=1),
        event('m-first', 1, 'order', 2000, 4, 'decision', target=1),
        event('peer-history', 1, 'peer', 1000, 1, 'refund'),
        event('peer-decision', 1, 'peer', 2100, 1, 'decision', target=1),
        event('peer-two-history', 1, 'peer-two', 1000, 1, 'click'),
        event('peer-two-decision', 1, 'peer-two', 2200, 1, 'decision', target=0),
        event('held-history', 1, 'held', 1000, 1, 'purchase', 50.0),
        event('held-decision', 1, 'held', 2000, 2, 'decision', target=0),
    ]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['held']}
    result, want = run(events, policy); assert result.returncode == 0; assert_outputs(*want)

def test_holdout_policy_never_contributes_to_normalization():
    """Changing held-out entities changes split labels and train-only normalizer values."""
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['rivulet']}
    result, want = run(policy=policy); assert result.returncode == 0; assert_outputs(*want)

def test_zero_variance_uses_unit_scale():
    """A constant training feature column is normalized with scale one rather than NaN or infinity."""
    events = [event('a', 1, 'north', 1000, 1, 'decision', target=0), event('b', 1, 'south', 2000, 2, 'decision', target=1), event('c', 1, 'east', 2500, 3, 'decision', target=0), event('d', 1, 'hazel', 3000, 4, 'decision', target=0)]
    result, want = run(events); assert result.returncode == 0; assert_outputs(*want)

def test_robust_statistics_use_even_median_and_mad_rules():
    """The all-train robust manifest must average central values before deriving a median absolute deviation."""
    events = [
        event('north-decision', 1, 'north', 1000, 1, 'decision', target=0),
        event('south-click', 1, 'south', 1100, 2, 'click'), event('south-decision', 1, 'south', 2000, 3, 'decision', target=1),
        event('east-click-1', 1, 'east', 2100, 4, 'click'), event('east-click-2', 1, 'east', 2200, 5, 'click'), event('east-decision', 1, 'east', 3000, 6, 'decision', target=0),
        event('west-click-1', 1, 'west', 3100, 7, 'click'), event('west-click-2', 1, 'west', 3200, 8, 'click'), event('west-click-3', 1, 'west', 3300, 9, 'click'), event('west-decision', 1, 'west', 4000, 10, 'decision', target=1),
        event('held-decision', 1, 'held', 5000, 11, 'decision', target=0),
    ]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['held']}
    result, want = run(events, policy); assert result.returncode == 0; assert_outputs(*want)
    assert want[1]['robust_medians']['click_count_5m'] == 1.5
    assert want[1]['robust_mads']['click_count_5m'] == 1.0

def test_fewer_than_three_training_entities_cannot_form_calibration_folds():
    """All three deterministic calibration folds need a train entity before fold-disjoint calibration."""
    events = [event('train', 1, 'north', 1000, 1, 'decision', target=0), event('test', 1, 'hazel', 2000, 2, 'decision', target=1)]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    assert_semantic_rejection(execute(events, policy))

@pytest.mark.parametrize('case', range(16))
def test_combined_reconciliation_window_split_and_normalizer_matrix(case):
    """A deterministic matrix combines revisions, both window edges, held-out data, and normalizer fitting."""
    anchor = 10_000_000 + case * 10000
    train, peer, peer_two, held = f'train-{case}', f'peer-{case}', f'peer-two-{case}', f'held-{case}'
    revised_kind = ('refund', 'purchase', 'click')[case % 3]
    revised_entity = train if case % 3 != 2 else f'elsewhere-{case}'
    revised_time = anchor - 200 if case % 3 != 1 else anchor + 200
    events = [
        event('one-hour-left', 1, train, anchor - 3600000, 1, 'click'),
        event('five-minute-left', 1, train, anchor - 300000, 2, 'click'),
        event('purchase', 1, train, anchor - 1000 - case, 3, 'purchase', float(case - 8)),
        event('refund', 1, train, anchor - 100, 4, 'refund', float(case + 1)),
        event('tie', 1, train, anchor, 5, 'purchase', 777.0),
        event('future', 1, train, anchor + 1, 6, 'click'),
        event('revised', 1, train, anchor - 50, 7, 'purchase', 999.0),
        event('revised', 2, revised_entity, revised_time, 8, revised_kind, float(case + 3), available_ms=max(revised_time, anchor + 100 if case % 2 else anchor - 10)),
        event('held-history', 1, held, anchor - 10, 9, 'purchase', 100000.0 + case),
        event('train-decision', 1, train, anchor, 10, 'decision', target=case % 2),
        event('held-decision', 1, held, anchor + 300, 11, 'decision', target=(case + 1) % 2),
        event('peer-history', 1, peer, anchor - 20, 12, 'refund', float(case)),
        event('peer-decision', 1, peer, anchor + 500, 13, 'decision', target=case % 2),
        event('peer-two-history', 1, peer_two, anchor - 30, 14, 'click'),
        event('peer-two-decision', 1, peer_two, anchor + 700, 15, 'decision', target=(case + 1) % 2),
    ]
    profiles = ([300000, 3600000], [300000, 900000, 3600000], [900000, 3600000])
    policy = {'window_ms': profiles[case % len(profiles)], 'holdout_entities': [held]}
    result, want = run(events, policy); assert result.returncode == 0; assert_outputs(*want)

def test_equal_revisions_are_rejected_before_artifacts():
    """Two records tied at the greatest revision cannot be reconciled into one live record."""
    events = base_events() + [event('n-p1', 1, 'north', 1200, 41, 'purchase', 6.0)]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    assert_semantic_rejection(execute(events, policy))

@pytest.mark.parametrize('policy', [
    {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel', 'hazel']},
    {'window_ms': [300000.0, 3600000], 'holdout_entities': ['hazel']},
    {'window_ms': [300000, 3600000], 'holdout_entities': [7]},
    {'window_ms': [3600000, 300000], 'holdout_entities': ['hazel']},
    {'window_ms': [300000, 3600000, 7200000], 'holdout_entities': ['hazel']},
    {'window_ms': [900000], 'holdout_entities': ['hazel']},
    {'window_ms': [300000, 300000], 'holdout_entities': ['hazel']},
    {'window_ms': [True, 3600000], 'holdout_entities': ['hazel']},
    {'window_ms': [300000, 3600000], 'holdout_entities': None},
    {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel'], 'extra': 1},
    {'window_ms': [300000, 3600000]},
])
def test_malformed_policy_fails_without_output_artifacts(policy):
    """Only documented canonical 2- or 3-window profiles and duplicate-free string holdouts are valid."""
    result = execute(base_events(), policy); assert result.returncode != 0; assert all(not (OUT / name).exists() for name in ARTIFACTS)

def test_all_holdout_policy_fails_without_output_artifacts():
    """A valid bundle requires at least one train anchor from which to fit the normalizer."""
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['north', 'hazel', 'rivulet', 'south']}
    assert_semantic_rejection(execute(base_events(), policy))

def test_available_time_before_event_time_is_rejected_in_an_otherwise_valid_stream():
    """Availability validation must be decisive rather than masked by a separate empty-fold failure."""
    events = [
        event('north-decision', 1, 'north', 1000, 1, 'decision', target=1),
        event('south-decision', 1, 'south', 2000, 2, 'decision', target=0),
        event('east-decision', 1, 'east', 3000, 3, 'decision', target=1),
        event('held-decision', 1, 'held', 4000, 4, 'decision', target=0),
        event('bad-availability', 1, 'north', 1500, 5, 'click', available_ms=1499),
    ]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['held']}
    result = execute(events, policy)
    assert result.returncode != 0 and all(not (OUT / name).exists() for name in ARTIFACTS)

@pytest.mark.parametrize('case', range(8))
def test_boolean_decision_target_is_rejected_in_an_otherwise_valid_stream(case):
    """A boolean must not be accepted through Python's integer subclass when the rest of the bundle is valid."""
    record_id, entity, event_ms = (('n-d1', 'north', 1300), ('s-d1', 'south', 1500), ('r-d1', 'rivulet', 1300), ('h-d1', 'hazel', 1300))[case % 4]
    events = base_events() + [event(record_id, 2, entity, event_ms, 80 + case, 'decision', target=bool(case % 2))]
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    result = execute(events, policy)
    assert result.returncode != 0 and all(not (OUT / name).exists() for name in ARTIFACTS)

@pytest.mark.parametrize('bad', [
    event('bad', 1, 'north', 1, 1, 'decision', target=None),
    event('bad', -1, 'north', 1, 1, 'click'),
    event('bad', 1, 'north', 1, 1, 'other'),
    event('bad', 1, 'north', 1, 1, 'click', target=1),
    event('', 1, 'north', 1, 1, 'click'),
    event('bad', 1, '', 1, 1, 'click'),
    event('bad', True, 'north', 1, 1, 'click'),
    event('bad', 1, 'north', True, 1, 'click'),
    event('bad', 1, 'north', 1, 1, 'click', available_ms=True),
    event('bad', 1, 'north', 1, 1, 'click', available_ms=0),
    event('bad', 1, 'north', 1, -1, 'click'),
    event('bad', 1, 'north', 1, 1, 'purchase', amount=True),
    event('bad', 1, 'north', 1, 1, 'purchase', amount=math.inf),
    {**event('bad', 1, 'north', 1, 1, 'click'), 'unexpected': 1},
    {key: value for key, value in event('bad', 1, 'north', 1, 1, 'click').items() if key != 'available_ms'},
])
def test_invalid_input_fails_without_output_artifacts(bad):
    """Malformed records are rejected before either required output is written."""
    policy = {'window_ms': [300000, 3600000], 'holdout_entities': ['hazel']}
    result = execute([bad], policy); assert result.returncode != 0; assert all(not (OUT / name).exists() for name in ARTIFACTS)

@pytest.mark.parametrize('events_text, policy_text', [
    ('not valid json\n', json.dumps({'window_ms': [300000, 3600000], 'holdout_entities': []})),
    (json.dumps(event('a', 1, 'north', 1, 1, 'decision', target=1)) + '\n', '{not valid json}'),
    ('\n', json.dumps({'window_ms': [300000, 3600000], 'holdout_entities': []})),
])
def test_malformed_serialized_inputs_fail_without_output_artifacts(events_text, policy_text):
    """JSON syntax errors and a stream without a live train decision cannot create partial outputs."""
    result = execute_raw(events_text, policy_text); assert result.returncode != 0; assert all(not (OUT / name).exists() for name in ARTIFACTS)
