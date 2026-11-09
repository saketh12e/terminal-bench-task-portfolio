import hashlib, json, math, os
from pathlib import Path

ROOT = Path('/app')
CHECKPOINT = ROOT / 'output' / 'feature_checkpoint.json'
FEATURES = ('click_count', 'purchase_net', 'refund_count', 'open_purchase_amount', 'oldest_open_purchase_age_ms', 'activity_recency_ms', 'purchase_recency_ms', 'prior_decision_count', 'prior_positive_rate')
SUFFIX = {300000: '5m', 900000: '15m', 3600000: '1h'}

def raw_names(windows):
    return tuple(f'{feature}_{SUFFIX[window]}' for window in windows for feature in FEATURES)

def stable_purchase_sum(values):
    values = list(values)
    try:
        return math.fsum(values)
    except OverflowError:
        # A partial float sum can overflow even when cancellation leaves a finite result.
        # Binary denominators are powers of two, so integer scaling loses no information.
        ratios = [value.as_integer_ratio() for value in values]
        denominator = max(divisor for _, divisor in ratios)
        numerator = sum(value * (denominator // divisor) for value, divisor in ratios)
        return numerator / denominator

def median(values):
    ordered = sorted(values); middle = len(ordered) // 2
    return float(ordered[middle]) if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0

def unsettled_purchases(history):
    """Consume positive refunds against positive purchases in canonical FIFO activity order."""
    pending = []
    for event in sorted(history, key=lambda item: (item['event_ms'], item['ingest_seq'], item['record_id'])):
        amount = float(event['amount'])
        if event['kind'] == 'purchase' and amount > 0:
            pending.append([event['event_ms'], amount])
        elif event['kind'] == 'refund' and amount > 0:
            remaining = amount
            while remaining > 0 and pending:
                consumed = min(remaining, pending[0][1]); remaining -= consumed; pending[0][1] -= consumed
                if pending[0][1] == 0: pending.pop(0)
    return pending

def read_inputs():
    events = []
    for line in (ROOT / 'data/events.jsonl').read_text(encoding='utf-8').splitlines():
        if line: events.append(json.loads(line))
    return events, json.loads((ROOT / 'data/policy.json').read_text(encoding='utf-8'))

def validate(events, policy):
    required = {'record_id', 'revision', 'entity_id', 'event_ms', 'available_ms', 'ingest_seq', 'kind', 'amount', 'target'}
    windows = policy.get('window_ms') if isinstance(policy, dict) else None
    holdout = policy.get('holdout_entities') if isinstance(policy, dict) else None
    if set(policy) != {'window_ms', 'holdout_entities'} or type(windows) is not list or len(windows) not in (2, 3) or any(type(value) is not int for value in windows) or windows != sorted(windows) or len(set(windows)) != len(windows) or any(value not in SUFFIX for value in windows) or type(holdout) is not list or any(type(value) is not str for value in holdout) or len(set(holdout)) != len(holdout): raise ValueError('policy')
    for event in events:
        if set(event) != required or not isinstance(event['record_id'], str) or not event['record_id'] or not isinstance(event['entity_id'], str) or not event['entity_id']: raise ValueError('record')
        if type(event['revision']) is not int or event['revision'] < 0 or type(event['event_ms']) is not int or type(event['available_ms']) is not int or event['available_ms'] < event['event_ms'] or type(event['ingest_seq']) is not int or event['ingest_seq'] < 0: raise ValueError('integer')
        if event['kind'] not in {'click', 'purchase', 'refund', 'decision'} or type(event['amount']) not in (int, float) or not math.isfinite(event['amount']): raise ValueError('kind')
        if event['kind'] == 'decision' and not (type(event['target']) is int and event['target'] in (0, 1)): raise ValueError('target')
        if event['kind'] != 'decision' and event['target'] is not None: raise ValueError('target')

def build(events, policy):
    raw = raw_names(policy['window_ms'])
    versions = {}
    for event in events:
        versions.setdefault(event['record_id'], []).append(event)
    def choose(candidates):
        greatest = max(event['revision'] for event in candidates)
        winners = [event for event in candidates if event['revision'] == greatest]
        if len(winners) != 1: raise ValueError('equal revision')
        return winners[0]
    live = {record_id: choose(candidates) for record_id, candidates in versions.items()}
    values = list(live.values()); heldout = set(policy['holdout_entities'])
    anchors = sorted((event for event in values if event['kind'] == 'decision'), key=lambda event: (event['event_ms'], event['ingest_seq'], event['record_id']))
    rows = []
    for anchor in anchors:
        row = {'anchor_id': anchor['record_id'], 'entity_id': anchor['entity_id'], 'anchor_ms': anchor['event_ms'], 'split': 'test' if anchor['entity_id'] in heldout else 'train', 'target': anchor['target']}
        selected = []
        for candidates in versions.values():
            known = [event for event in candidates if event['available_ms'] <= anchor['event_ms']]
            if known:
                event = choose(known)
                if event['entity_id'] == anchor['entity_id'] and event['event_ms'] < anchor['event_ms']: selected.append(event)
        activity = [event for event in selected if event['kind'] in {'click', 'purchase', 'refund'}]
        pending = unsettled_purchases(activity)
        for window in policy['window_ms']:
            suffix = SUFFIX[window]
            lower = anchor['event_ms'] - window
            history = [event for event in activity if lower <= event['event_ms']]
            prior_decisions = [event for event in selected if event['kind'] == 'decision' and lower <= event['event_ms']]
            row[f'click_count_{suffix}'] = sum(event['kind'] == 'click' for event in history)
            row[f'purchase_net_{suffix}'] = stable_purchase_sum(event['amount'] for event in history if event['kind'] == 'purchase')
            row[f'refund_count_{suffix}'] = sum(event['kind'] == 'refund' for event in history)
            window_pending = [item for item in pending if lower <= item[0]]
            open_amount = math.fsum(balance for _, balance in window_pending); oldest_open_ms = window_pending[0][0] if window_pending else None
            row[f'open_purchase_amount_{suffix}'] = open_amount
            row[f'oldest_open_purchase_age_ms_{suffix}'] = anchor['event_ms'] - oldest_open_ms if oldest_open_ms is not None else window
            row[f'activity_recency_ms_{suffix}'] = anchor['event_ms'] - max((event['event_ms'] for event in history), default=anchor['event_ms'] - window)
            row[f'purchase_recency_ms_{suffix}'] = anchor['event_ms'] - max((event['event_ms'] for event in history if event['kind'] == 'purchase'), default=anchor['event_ms'] - window)
            row[f'prior_decision_count_{suffix}'] = len(prior_decisions)
            row[f'prior_positive_rate_{suffix}'] = (sum(event['target'] for event in prior_decisions) + 1.0) / (len(prior_decisions) + 2.0)
        rows.append(row)
    train = [row for row in rows if row['split'] == 'train']
    if not train: raise ValueError('no train anchors')
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
    if any(anchor_count == 0 for anchor_count, _, _ in fold_stats): raise ValueError('empty calibration fold')
    for row in rows: row['calibration_fold'] = folds[row['entity_id']] if row['split'] == 'train' else None
    means = {name: math.fsum(row[name] for row in train) / len(train) for name in raw}
    scales = {name: math.sqrt(math.fsum((row[name] - means[name]) ** 2 for row in train) / len(train)) for name in raw}
    scales = {name: scale if scale else 1.0 for name, scale in scales.items()}
    robust_medians = {name: median([row[name] for row in train]) for name in raw}
    robust_mads = {name: median([abs(row[name] - robust_medians[name]) for row in train]) or 1.0 for name in raw}
    for row in rows:
        cohort = train if row['split'] == 'test' else [candidate for candidate in train if candidate['calibration_fold'] != row['calibration_fold']]
        if not cohort: raise ValueError('no calibration cohort')
        cohort_means = {name: math.fsum(candidate[name] for candidate in cohort) / len(cohort) for name in raw}
        cohort_scales = {name: math.sqrt(math.fsum((candidate[name] - cohort_means[name]) ** 2 for candidate in cohort) / len(cohort)) for name in raw}
        cohort_scales = {name: scale if scale else 1.0 for name, scale in cohort_scales.items()}
        cohort_medians = {name: median([candidate[name] for candidate in cohort]) for name in raw}
        cohort_mads = {name: median([abs(candidate[name] - cohort_medians[name]) for candidate in cohort]) or 1.0 for name in raw}
        for name in raw: row['z_' + name] = (row[name] - cohort_means[name]) / cohort_scales[name]
        for name in raw: row['r_' + name] = (row[name] - cohort_medians[name]) / cohort_mads[name]
    manifest = {'schema_version': 1, 'input_rows': len(events), 'live_rows': len(values), 'anchors': len(rows), 'train_anchors': len(train), 'feature_order': list(raw), 'means': means, 'scales': scales, 'robust_medians': robust_medians, 'robust_mads': robust_mads}
    return rows, manifest

def policy_digest(policy):
    return hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

def interrupted(events, policy, count):
    if count < 1 or count >= len(events): raise ValueError('interrupt count')
    output = ROOT / 'output'; output.mkdir(exist_ok=True)
    CHECKPOINT.write_text(json.dumps({'schema_version': 1, 'policy_sha256': policy_digest(policy), 'consumed_rows': count, 'consumed_events': events[:count]}, sort_keys=True, separators=(',', ':')), encoding='utf-8')

def resumed(events, policy):
    checkpoint = json.loads(CHECKPOINT.read_text(encoding='utf-8'))
    if set(checkpoint) != {'schema_version', 'policy_sha256', 'consumed_rows', 'consumed_events'} or type(checkpoint['schema_version']) is not int or checkpoint['schema_version'] != 1 or checkpoint['policy_sha256'] != policy_digest(policy) or type(checkpoint['consumed_rows']) is not int or checkpoint['consumed_rows'] < 1 or type(checkpoint['consumed_events']) is not list or len(checkpoint['consumed_events']) != checkpoint['consumed_rows']: raise ValueError('checkpoint')
    return checkpoint['consumed_events'] + events

def main():
    events, policy = read_inputs()
    interrupt = os.environ.get('INTERRUPT_AFTER_RECORD'); resume = os.environ.get('RESUME')
    if resume is not None:
        if resume != '1': raise ValueError('resume')
        events = resumed(events, policy)
    validate(events, policy)
    # Validate the reconstructed stream's semantics before publishing a checkpoint.
    # Schema validation alone cannot detect revision ties or empty calibration folds.
    rows, manifest = build(events, policy)
    if interrupt is not None:
        if not interrupt.isdecimal(): raise ValueError('interrupt')
        count = int(interrupt)
        if resume is not None and count <= json.loads(CHECKPOINT.read_text(encoding='utf-8'))['consumed_rows']: raise ValueError('interrupt cannot rewind')
        interrupted(events, policy, count); raise SystemExit(75)
    output = ROOT / 'output'; output.mkdir(exist_ok=True)
    (output / 'feature_bundle.jsonl').write_text(''.join(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n' for row in rows), encoding='utf-8')
    (output / 'feature_manifest.json').write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':')), encoding='utf-8')
    if resume is not None: CHECKPOINT.unlink()

if __name__ == '__main__': main()
