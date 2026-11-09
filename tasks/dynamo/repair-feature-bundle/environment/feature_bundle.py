"""Feature-bundle builder with several subtle leakage and recovery defects."""

import json
import math
from pathlib import Path

ROOT = Path('/app')
OUTPUT = ROOT / 'output'
FEATURES = ('click_count', 'purchase_net', 'refund_count', 'open_purchase_amount', 'oldest_open_purchase_age_ms', 'activity_recency_ms', 'purchase_recency_ms', 'prior_decision_count', 'prior_positive_rate')
SUFFIX = {300000: '5m', 900000: '15m', 3600000: '1h'}

def raw_names(windows):
    return tuple(f'{feature}_{SUFFIX[window]}' for window in windows for feature in FEATURES)


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    return float(ordered[middle]) if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0


def read_inputs():
    events = [json.loads(line) for line in (ROOT / 'data' / 'events.jsonl').read_text(encoding='utf-8').splitlines() if line]
    policy = json.loads((ROOT / 'data' / 'policy.json').read_text(encoding='utf-8'))
    return events, policy


def reconcile_final(events):
    """Keep a current record for each ID, assuming all corrections are harmless."""
    current = {}
    for event in events:
        old = current.get(event['record_id'])
        if old is None or event['revision'] >= old['revision']:
            current[event['record_id']] = event
    return list(current.values())


def rows_for(events, policy):
    """Build rolling features from the current records."""
    rows = []
    for anchor in (event for event in events if event['kind'] == 'decision'):
        row = {
            'anchor_id': anchor['record_id'],
            'entity_id': anchor['entity_id'],
            'anchor_ms': anchor['event_ms'],
            'split': 'train',
            'target': anchor['target'],
        }
        for window in policy['window_ms']:
            suffix = SUFFIX[window]
            history = [
                event for event in events
                if event['entity_id'] == anchor['entity_id']
                and event['kind'] in {'click', 'purchase', 'refund'}
                and anchor['event_ms'] - window <= event['event_ms'] <= anchor['event_ms']
            ]
            row[f'click_count_{suffix}'] = sum(event['kind'] == 'click' for event in history)
            row[f'purchase_net_{suffix}'] = float(sum(event['amount'] for event in history if event['kind'] == 'purchase'))
            row[f'refund_count_{suffix}'] = sum(event['kind'] == 'refund' for event in history)
            gross_purchase = sum(max(float(event['amount']), 0.0) for event in history if event['kind'] == 'purchase')
            applied_refund = sum(max(float(event['amount']), 0.0) for event in history if event['kind'] == 'refund')
            row[f'open_purchase_amount_{suffix}'] = max(0.0, gross_purchase - applied_refund)
            oldest = min((event['event_ms'] for event in history if event['kind'] == 'purchase' and event['amount'] > 0), default=None)
            row[f'oldest_open_purchase_age_ms_{suffix}'] = anchor['event_ms'] - oldest if oldest is not None and row[f'open_purchase_amount_{suffix}'] else window
            row[f'activity_recency_ms_{suffix}'] = anchor['event_ms'] - max((event['event_ms'] for event in history), default=anchor['event_ms'] - window)
            row[f'purchase_recency_ms_{suffix}'] = anchor['event_ms'] - max((event['event_ms'] for event in history if event['kind'] == 'purchase'), default=anchor['event_ms'] - window)
            prior = [event for event in events if event['entity_id'] == anchor['entity_id'] and event['kind'] == 'decision' and anchor['event_ms'] - window <= event['event_ms'] < anchor['event_ms']]
            row[f'prior_decision_count_{suffix}'] = len(prior)
            row[f'prior_positive_rate_{suffix}'] = (sum(event['target'] for event in prior) + 1.0) / (len(prior) + 2.0)
        rows.append(row)
    return rows


def normalize(rows, raw):
    """Standardize the bundle with one global population for all score families."""
    means = {name: sum(row[name] for row in rows) / len(rows) for name in raw}
    scales = {
        name: math.sqrt(sum((row[name] - means[name]) ** 2 for row in rows) / len(rows)) or 1.0
        for name in raw
    }
    robust_medians = {name: median([row[name] for row in rows]) for name in raw}
    robust_mads = {name: median([abs(row[name] - robust_medians[name]) for row in rows]) or 1.0 for name in raw}
    for index, row in enumerate(rows):
        row['calibration_fold'] = index % 3
        for name in raw:
            row['z_' + name] = (row[name] - means[name]) / scales[name]
            row['r_' + name] = (row[name] - robust_medians[name]) / robust_mads[name]
    return means, scales, robust_medians, robust_mads


def main():
    events, policy = read_inputs()
    live = reconcile_final(events)
    rows = rows_for(live, policy)
    raw = raw_names(policy['window_ms'])
    means, scales, robust_medians, robust_mads = normalize(rows, raw)
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / 'feature_bundle.jsonl').write_text(
        ''.join(json.dumps(row, sort_keys=True, separators=(',', ':')) + '\n' for row in rows),
        encoding='utf-8',
    )
    manifest = {
        'schema_version': 1,
        'input_rows': len(events),
        'live_rows': len(live),
        'anchors': len(rows),
        'train_anchors': len(rows),
        'feature_order': list(raw),
        'means': means,
        'scales': scales,
        'robust_medians': robust_medians,
        'robust_mads': robust_mads,
    }
    (OUTPUT / 'feature_manifest.json').write_text(
        json.dumps(manifest, sort_keys=True, separators=(',', ':')),
        encoding='utf-8',
    )


if __name__ == '__main__':
    main()
