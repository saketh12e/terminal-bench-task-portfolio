import csv
import hashlib
import importlib
import io
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path


APP_ROOT = Path(os.environ.get("APP_ROOT", "/app"))
TEST_ROOT = Path(os.environ.get("TEST_ROOT", "/tests"))

QTY_QUANT = Decimal("0.001")
MONEY_QUANT = Decimal("0.01")
MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")
QTY_RE = re.compile(r"^-?\d+\.\d{3}$")

SETTLED_FIELDS = [
    "order_id",
    "line_id",
    "fulfillment_id",
    "sku",
    "ship_from_location",
    "local_service_date",
    "currency",
    "settled_quantity_each",
    "unit_price",
    "gross_amount",
    "discount_amount",
    "adjustment_amount",
    "net_amount",
]

EXCEPTION_FIELDS = [
    "exception_code",
    "order_id",
    "line_id",
    "fulfillment_id",
    "source_row_id",
    "detail",
]

LINEAGE_FIELDS = [
    "row_type",
    "status",
    "order_id",
    "line_id",
    "fulfillment_id",
    "event_key",
    "selected_source_row_id",
    "settled_key",
    "settlement_sku",
    "ship_from_location",
    "local_service_date",
    "applied_override_source_row_ids",
    "price_source_row_id",
    "normalized_quantity_each",
    "pre_allocation_gross_amount",
    "detail",
]

SUMMARY_KEYS = [
    "settled_row_count",
    "exception_row_count",
    "lineage_row_count",
    "lineage_sha256",
    "currency_totals",
    "exception_counts",
]


def rules_module():
    sys.path.insert(0, str(APP_ROOT))
    return importlib.import_module("settlement_engine.rules")


def write_rows(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def csv_payload(fields, rows):
    fh = io.StringIO(newline="")
    writer = csv.DictWriter(fh, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return fh.getvalue()


def write_minimal_batch(batch_dir, orders, events, *, overrides=None, aliases=None, conversions=None, locations=None, prices=None):
    write_rows(
        batch_dir / "order_lines.csv",
        ["order_id", "line_id", "sku", "currency", "total_discount", "total_adjustment", "discount_basis", "adjustment_basis"],
        orders,
    )
    write_rows(
        batch_dir / "fulfillment_events.csv",
        ["event_key", "source_row_id", "order_id", "line_id", "fulfillment_id", "sku", "quantity", "uom", "ship_from_location", "event_at", "effective_at", "ingested_at", "sequence_id", "is_void"],
        events,
    )
    write_rows(
        batch_dir / "fulfillment_overrides.csv",
        ["override_key", "source_row_id", "event_key", "quantity_delta", "uom", "ship_from_location", "event_at", "effective_at", "sequence_id", "is_void"],
        overrides or [],
    )
    write_rows(
        batch_dir / "sku_aliases.csv",
        ["order_sku", "event_sku", "settlement_sku", "quantity_multiplier"],
        aliases or [],
    )
    write_rows(
        batch_dir / "packaging_conversions.csv",
        ["sku", "uom", "each_per_unit"],
        conversions or [{"sku": "SKU-X", "uom": "EACH", "each_per_unit": "1"}],
    )
    write_rows(
        batch_dir / "locations.csv",
        ["ship_from_location", "utc_offset_minutes"],
        locations or [{"ship_from_location": "LOC_A", "utc_offset_minutes": "0"}],
    )
    write_rows(
        batch_dir / "price_history.csv",
        ["sku", "currency", "unit_price", "effective_at", "sequence_id", "source_row_id"],
        prices or [{"sku": "SKU-X", "currency": "USD", "unit_price": "1.00", "effective_at": "2026-01-01T00:00:00Z", "sequence_id": "1", "source_row_id": "PX1"}],
    )


def read_csv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def parse_dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_bool(value):
    return value.strip().lower() in {"true", "1", "yes", "y"}


def quantity_str(value):
    return format(value.quantize(QTY_QUANT, rounding=ROUND_HALF_UP), "f")


def money_str(value):
    return format(value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP), "f")


def current_record(rows, key_func):
    selected = {}
    for row in rows:
        key = key_func(row)
        rank = (
            parse_dt(row["effective_at"]),
            int(row["sequence_id"]),
            row["source_row_id"],
        )
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, row)
    return [row for _, row in selected.values()]


def selected_price(price_rows, sku, currency, event_at):
    candidates = [
        row
        for row in price_rows.get((sku, currency), [])
        if parse_dt(row["effective_at"]) <= event_at
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            parse_dt(row["effective_at"]),
            int(row["sequence_id"]),
            row["source_row_id"],
        ),
    )


def settled_sort_key(row):
    return (
        row["order_id"],
        row["line_id"],
        row["fulfillment_id"],
        row["sku"],
        row["ship_from_location"],
        row["local_service_date"],
    )


def exception_sort_key(row):
    return (
        row["exception_code"],
        row["order_id"],
        row["line_id"],
        row["fulfillment_id"],
        row["source_row_id"],
    )


def lineage_sort_key(row):
    return (
        row["row_type"],
        row["status"],
        row["order_id"],
        row["line_id"],
        row["fulfillment_id"],
        row["event_key"],
        row["selected_source_row_id"],
    )


def lineage_sha256(rows):
    return hashlib.sha256(csv_payload(LINEAGE_FIELDS, rows).encode()).hexdigest()


def exception_for(code, event, detail):
    return {
        "exception_code": code,
        "order_id": event["order_id"],
        "line_id": event["line_id"],
        "fulfillment_id": event["fulfillment_id"],
        "source_row_id": event["source_row_id"],
        "detail": detail,
    }


def cents_toward_zero(value):
    if value >= 0:
        return int(value.to_integral_value(rounding=ROUND_FLOOR))
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def allocation_weight(row, basis):
    if basis == "quantity":
        return row["_quantity"]
    if basis == "gross":
        return row["_gross"].quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
    if basis == "equal":
        return Decimal("1")
    raise ValueError(f"unknown allocation basis: {basis}")


def allocate_cents(total_money, rows, basis):
    total_cents = int((Decimal(total_money) * 100).to_integral_value())
    if total_cents == 0 or not rows:
        return [0 for _ in rows]

    weights = [allocation_weight(row, basis) for row in rows]
    total_weight = sum(weights)
    if total_weight == 0:
        return [0 for _ in rows]

    exact = [Decimal(total_cents) * weight / total_weight for weight in weights]
    base = [cents_toward_zero(value) for value in exact]
    residual = total_cents - sum(base)
    order = sorted(
        range(len(rows)),
        key=lambda idx: (
            -abs(exact[idx] - Decimal(base[idx])),
            settled_sort_key(rows[idx]),
        ),
    )
    cents = list(base)
    step = 1 if residual > 0 else -1
    for idx in order[: abs(residual)]:
        cents[idx] += step
    return cents


def cents_to_money(cents):
    return Decimal(cents) / Decimal(100)


def field_value(row, field):
    return row.get(field, "").strip()


def convert_quantity(conversions, sku, quantity, uom):
    factor = conversions.get((sku, uom))
    if factor is None:
        return None
    return Decimal(quantity) * factor


def expected_outputs(input_dir):
    orders = {
        (row["order_id"], row["line_id"]): row
        for row in read_csv(input_dir / "order_lines.csv")
    }
    event_rows = read_csv(input_dir / "fulfillment_events.csv")
    override_rows = read_csv(input_dir / "fulfillment_overrides.csv")
    alias_rows = read_csv(input_dir / "sku_aliases.csv")
    conversions = {
        (row["sku"], row["uom"]): Decimal(row["each_per_unit"])
        for row in read_csv(input_dir / "packaging_conversions.csv")
    }
    aliases = {
        (row["order_sku"], row["event_sku"]): row
        for row in alias_rows
    }
    selected_overrides = defaultdict(list)
    for override in current_record(override_rows, lambda row: row["override_key"]):
        if not parse_bool(override["is_void"]):
            selected_overrides[override["event_key"]].append(override)
    for event_key in selected_overrides:
        selected_overrides[event_key].sort(key=lambda row: row["override_key"])
    locations = {
        row["ship_from_location"]: int(row["utc_offset_minutes"])
        for row in read_csv(input_dir / "locations.csv")
    }
    prices = defaultdict(list)
    for row in read_csv(input_dir / "price_history.csv"):
        prices[(row["sku"], row["currency"])].append(row)

    settled_by_key = {}
    exceptions = []
    lineage = []

    def record_exception(event, code, detail, *, overrides=(), settlement_sku="", final_location=""):
        exceptions.append(exception_for(code, event, detail))
        lineage.append(
            {
                "row_type": "exception",
                "status": code,
                "order_id": event["order_id"],
                "line_id": event["line_id"],
                "fulfillment_id": event["fulfillment_id"],
                "event_key": event["event_key"],
                "selected_source_row_id": event["source_row_id"],
                "settled_key": "",
                "settlement_sku": settlement_sku,
                "ship_from_location": final_location,
                "local_service_date": "",
                "applied_override_source_row_ids": ";".join(
                    override["source_row_id"] for override in overrides
                ),
                "price_source_row_id": "",
                "normalized_quantity_each": "",
                "pre_allocation_gross_amount": "",
                "detail": detail,
            }
        )

    for event in current_record(event_rows, lambda row: row["event_key"]):
        if parse_bool(event["is_void"]):
            continue

        order = orders.get((event["order_id"], event["line_id"]))
        if order is None:
            record_exception(event, "unmatched_order_line", "order line not found")
            continue

        alias_multiplier = Decimal("1")
        settlement_sku = event["sku"]
        if event["sku"] != order["sku"]:
            alias = aliases.get((order["sku"], event["sku"]))
            if alias is None:
                record_exception(
                    event,
                    "sku_mismatch",
                    "event sku does not match order line",
                    settlement_sku=settlement_sku,
                    final_location=event["ship_from_location"],
                )
                continue
            settlement_sku = alias["settlement_sku"]
            alias_multiplier = Decimal(alias["quantity_multiplier"])

        converted_quantity = convert_quantity(
            conversions, event["sku"], event["quantity"], event["uom"]
        )
        if converted_quantity is None:
            record_exception(
                event,
                "missing_conversion",
                f"no conversion for {event['sku']} {event['uom']}",
                settlement_sku=settlement_sku,
                final_location=event["ship_from_location"],
            )
            continue

        final_location = event["ship_from_location"]
        final_event_at_text = event["event_at"]
        applied_overrides = []
        override_failed = False
        for override in selected_overrides.get(event["event_key"], []):
            applied_overrides.append(override)
            if field_value(override, "quantity_delta"):
                delta_quantity = convert_quantity(
                    conversions,
                    event["sku"],
                    override["quantity_delta"],
                    override["uom"],
                )
                if delta_quantity is None:
                    record_exception(
                        event,
                        "missing_conversion",
                        f"no conversion for {event['sku']} {override['uom']}",
                        overrides=applied_overrides,
                        settlement_sku=settlement_sku,
                        final_location=final_location,
                    )
                    override_failed = True
                    break
                converted_quantity += delta_quantity
            if field_value(override, "ship_from_location"):
                final_location = override["ship_from_location"]
            if field_value(override, "event_at"):
                final_event_at_text = override["event_at"]
        if override_failed:
            continue

        quantity = (converted_quantity * alias_multiplier).quantize(
            QTY_QUANT, rounding=ROUND_HALF_UP
        )
        if quantity <= 0:
            record_exception(
                event,
                "negative_settled_quantity",
                "normalized quantity is not positive",
                overrides=applied_overrides,
                settlement_sku=settlement_sku,
                final_location=final_location,
            )
            continue

        offset_minutes = locations.get(final_location)
        if offset_minutes is None:
            record_exception(
                event,
                "unresolved_timezone",
                f"no timezone offset for {final_location}",
                overrides=applied_overrides,
                settlement_sku=settlement_sku,
                final_location=final_location,
            )
            continue

        event_at = parse_dt(final_event_at_text)
        price = selected_price(prices, settlement_sku, order["currency"], event_at)
        if price is None:
            record_exception(
                event,
                "missing_current_price",
                f"no price for {settlement_sku} {order['currency']} at {final_event_at_text}",
                overrides=applied_overrides,
                settlement_sku=settlement_sku,
                final_location=final_location,
            )
            continue

        local_service_date = (event_at + timedelta(minutes=offset_minutes)).date().isoformat()
        unit_price = Decimal(price["unit_price"]).quantize(
            MONEY_QUANT, rounding=ROUND_HALF_UP
        )
        gross = (quantity * unit_price).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        key = (
            event["order_id"],
            event["line_id"],
            event["fulfillment_id"],
            settlement_sku,
            final_location,
            local_service_date,
        )
        lineage.append(
            {
                "row_type": "settled",
                "status": "settled",
                "order_id": event["order_id"],
                "line_id": event["line_id"],
                "fulfillment_id": event["fulfillment_id"],
                "event_key": event["event_key"],
                "selected_source_row_id": event["source_row_id"],
                "settled_key": "|".join(key),
                "settlement_sku": settlement_sku,
                "ship_from_location": final_location,
                "local_service_date": local_service_date,
                "applied_override_source_row_ids": ";".join(
                    override["source_row_id"] for override in applied_overrides
                ),
                "price_source_row_id": price["source_row_id"],
                "normalized_quantity_each": quantity_str(quantity),
                "pre_allocation_gross_amount": money_str(gross),
                "detail": "",
            }
        )
        if key not in settled_by_key:
            settled_by_key[key] = {
                "order_id": event["order_id"],
                "line_id": event["line_id"],
                "fulfillment_id": event["fulfillment_id"],
                "sku": settlement_sku,
                "ship_from_location": final_location,
                "local_service_date": local_service_date,
                "currency": order["currency"],
                "settled_quantity_each": "0.000",
                "unit_price": money_str(unit_price),
                "gross_amount": "0.00",
                "discount_amount": "0.00",
                "adjustment_amount": "0.00",
                "net_amount": "0.00",
                "_quantity": Decimal("0"),
                "_gross": Decimal("0"),
            }
        settled_by_key[key]["_quantity"] += quantity
        settled_by_key[key]["_gross"] += gross

    settled = sorted(settled_by_key.values(), key=settled_sort_key)
    by_line = defaultdict(list)
    for row in settled:
        by_line[(row["order_id"], row["line_id"])].append(row)

    for key, rows in by_line.items():
        order = orders[key]
        discount_cents = allocate_cents(
            order["total_discount"], rows, order["discount_basis"]
        )
        adjustment_cents = allocate_cents(
            order["total_adjustment"], rows, order["adjustment_basis"]
        )
        for row, discount, adjustment in zip(rows, discount_cents, adjustment_cents):
            gross = row["_gross"].quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
            discount_money = cents_to_money(discount)
            adjustment_money = cents_to_money(adjustment)
            row["settled_quantity_each"] = quantity_str(row["_quantity"])
            row["gross_amount"] = money_str(gross)
            row["discount_amount"] = money_str(discount_money)
            row["adjustment_amount"] = money_str(adjustment_money)
            row["net_amount"] = money_str(gross + discount_money + adjustment_money)

    settled_rows = [{field: row[field] for field in SETTLED_FIELDS} for row in settled]
    exception_rows = sorted(exceptions, key=exception_sort_key)
    lineage_rows = sorted(lineage, key=lineage_sort_key)

    currency_totals = defaultdict(lambda: defaultdict(Decimal))
    for row in settled_rows:
        for field in [
            "gross_amount",
            "discount_amount",
            "adjustment_amount",
            "net_amount",
        ]:
            currency_totals[row["currency"]][field] += Decimal(row[field])

    summary = {
        "settled_row_count": len(settled_rows),
        "exception_row_count": len(exception_rows),
        "lineage_row_count": len(lineage_rows),
        "lineage_sha256": lineage_sha256(lineage_rows),
        "currency_totals": [
            {
                "currency": currency,
                "gross_amount": money_str(values["gross_amount"]),
                "discount_amount": money_str(values["discount_amount"]),
                "adjustment_amount": money_str(values["adjustment_amount"]),
                "net_amount": money_str(values["net_amount"]),
            }
            for currency, values in sorted(currency_totals.items())
        ],
        "exception_counts": [
            {"exception_code": code, "row_count": count}
            for code, count in sorted(
                Counter(row["exception_code"] for row in exception_rows).items()
            )
        ],
    }
    return settled_rows, exception_rows, summary, lineage_rows


def read_output_csv(path, expected_fields):
    assert path.exists(), f"missing required output {path}"
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        assert reader.fieldnames == expected_fields
        return list(reader)


def read_summary(path):
    assert path.exists(), f"missing required output {path}"
    with open(path) as fh:
        summary = json.load(fh)
    assert set(summary.keys()) == set(SUMMARY_KEYS)
    assert isinstance(summary["settled_row_count"], int)
    assert isinstance(summary["exception_row_count"], int)
    assert isinstance(summary["lineage_row_count"], int)
    assert isinstance(summary["lineage_sha256"], str)
    assert re.fullmatch(r"[0-9a-f]{64}", summary["lineage_sha256"])
    assert isinstance(summary["currency_totals"], list)
    assert isinstance(summary["exception_counts"], list)
    for row in summary["currency_totals"]:
        assert set(row.keys()) == {
            "currency",
            "gross_amount",
            "discount_amount",
            "adjustment_amount",
            "net_amount",
        }
        for field in [
            "gross_amount",
            "discount_amount",
            "adjustment_amount",
            "net_amount",
        ]:
            assert MONEY_RE.match(row[field]), f"{field} is not canonical money"
    for row in summary["exception_counts"]:
        assert set(row.keys()) == {"exception_code", "row_count"}
        assert isinstance(row["row_count"], int)
    return summary


def load_outputs(output_dir):
    return (
        read_output_csv(output_dir / "settled_order_lines.csv", SETTLED_FIELDS),
        read_output_csv(output_dir / "settlement_exceptions.csv", EXCEPTION_FIELDS),
        read_summary(output_dir / "reconciliation_summary.json"),
        read_output_csv(output_dir / "settlement_lineage.csv", LINEAGE_FIELDS),
    )


def assert_sorted_unique(rows, key_func, label):
    keys = [key_func(row) for row in rows]
    assert keys == sorted(keys), f"{label} rows are not sorted by the required key"
    assert len(keys) == len(set(keys)), f"{label} key is not unique"


def assert_decimal_strings_are_canonical(settled_rows):
    for row in settled_rows:
        assert QTY_RE.match(row["settled_quantity_each"])
        for field in [
            "unit_price",
            "gross_amount",
            "discount_amount",
            "adjustment_amount",
            "net_amount",
        ]:
            assert MONEY_RE.match(row[field]), f"{field} is not canonical money"


def assert_outputs_match(actual_dir, input_dir):
    expected_settled, expected_exceptions, expected_summary, expected_lineage = expected_outputs(input_dir)
    actual_settled, actual_exceptions, actual_summary, actual_lineage = load_outputs(actual_dir)
    assert_sorted_unique(actual_settled, settled_sort_key, "settled")
    assert_sorted_unique(actual_exceptions, exception_sort_key, "exception")
    assert_sorted_unique(actual_lineage, lineage_sort_key, "lineage")
    assert_decimal_strings_are_canonical(actual_settled)
    assert actual_settled == expected_settled
    assert actual_exceptions == expected_exceptions
    assert actual_lineage == expected_lineage
    assert actual_summary["lineage_row_count"] == len(actual_lineage)
    assert actual_summary["lineage_sha256"] == lineage_sha256(actual_lineage)
    assert actual_summary == expected_summary


def run_pipeline(input_dir, output_dir):
    result = subprocess.run(
        [
            sys.executable,
            str(APP_ROOT / "settlement_pipeline.py"),
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_visible_batch_settled_rows_match_the_contract_oracle():
    """The visible settled CSV must match the contract oracle at the canonical grain."""
    assert_outputs_match(APP_ROOT / "output", APP_ROOT / "data" / "current_batch")


def test_visible_exceptions_have_exact_codes_details_and_sort_order():
    """The visible exception CSV must use the exact exception predicates and ordering."""
    _, exceptions, _, _ = load_outputs(APP_ROOT / "output")
    expected = expected_outputs(APP_ROOT / "data" / "current_batch")[1]
    assert exceptions == expected


def test_visible_summary_schema_and_totals_are_exact():
    """The visible JSON summary must use the pinned schema, counts, and Decimal-string totals."""
    summary = read_summary(APP_ROOT / "output" / "reconciliation_summary.json")
    assert summary == expected_outputs(APP_ROOT / "data" / "current_batch")[2]


def test_visible_lineage_rows_match_the_contract_oracle():
    """The visible lineage CSV must preserve selected source rows and provenance fields."""
    _, _, _, lineage = load_outputs(APP_ROOT / "output")
    assert lineage == expected_outputs(APP_ROOT / "data" / "current_batch")[3]


def test_visible_lineage_digest_matches_the_canonical_csv_payload():
    """The reconciliation summary digest must bind to the emitted lineage CSV."""
    _, _, summary, lineage = load_outputs(APP_ROOT / "output")
    assert summary["lineage_row_count"] == len(lineage)
    assert summary["lineage_sha256"] == lineage_sha256(lineage)


def test_visible_lineage_records_override_and_price_sources():
    """Lineage for corrected rows must expose the selected override and price source rows."""
    _, _, _, lineage = load_outputs(APP_ROOT / "output")
    row = next(row for row in lineage if row["event_key"] == "E-A100-L1-F3")
    assert row["applied_override_source_row_ids"] == "OV001"
    assert row["price_source_row_id"] == "P-ALPHA-001"
    assert row["settled_key"] == "A100|L1|F3|SKU-ALPHA|LOC_E|2026-02-01"


def test_visible_lineage_omits_current_void_events():
    """A fulfillment event whose current version is void must not leave a lineage row."""
    _, _, _, lineage = load_outputs(APP_ROOT / "output")
    assert "E-A100-L2-F5" not in {row["event_key"] for row in lineage}


def test_visible_allocation_preserves_order_line_totals():
    """Discount and adjustment cents must sum back to their source order-line totals."""
    settled, _, _, _ = load_outputs(APP_ROOT / "output")
    orders = {
        (row["order_id"], row["line_id"]): row
        for row in read_csv(APP_ROOT / "data" / "current_batch" / "order_lines.csv")
    }
    by_line = defaultdict(list)
    for row in settled:
        by_line[(row["order_id"], row["line_id"])].append(row)
    for key, rows in by_line.items():
        assert sum(Decimal(row["discount_amount"]) for row in rows) == Decimal(
            orders[key]["total_discount"]
        )
        assert sum(Decimal(row["adjustment_amount"]) for row in rows) == Decimal(
            orders[key]["total_adjustment"]
        )


def test_hidden_batch_outputs_match_contract_oracle(tmp_path):
    """The repaired pipeline must generalize to verifier-only fixture rows."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    assert_outputs_match(output_dir, input_dir)


def test_hidden_late_location_correction_recomputes_local_service_date(tmp_path):
    """A late current event that changes location must also change the local service date."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    settled, _, _, _ = load_outputs(output_dir)
    row = next(row for row in settled if row["order_id"] == "H100" and row["fulfillment_id"] == "F1")
    assert row["ship_from_location"] == "LOC_W"
    assert row["local_service_date"] == "2026-03-09"
    assert row["settled_quantity_each"] == "24.000"


def test_hidden_event_and_price_source_row_ties_are_resolved(tmp_path):
    """Equal effective time and sequence ties must fall through to lexicographic source_row_id."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    settled, _, _, _ = load_outputs(output_dir)
    row = next(row for row in settled if row["order_id"] == "H200" and row["fulfillment_id"] == "F3")
    assert row["settled_quantity_each"] == "4.000"
    assert row["unit_price"] == "7.30"


def test_hidden_residual_allocation_tie_uses_unique_output_sort_key(tmp_path):
    """Equal fractional remainders must be resolved by the unique settled output sort key."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    settled, _, _, _ = load_outputs(output_dir)
    rows = [row for row in settled if row["order_id"] == "H400"]
    assert [row["fulfillment_id"] for row in rows] == ["F6", "F7"]
    assert [row["discount_amount"] for row in rows] == ["-0.01", "0.00"]


def test_hidden_exception_key_set_and_counts_are_exact(tmp_path):
    """Hidden exceptions must be exact by key, code, detail, and summary count."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    _, exceptions, summary, _ = load_outputs(output_dir)
    assert exceptions == expected_outputs(input_dir)[1]
    assert summary["exception_counts"] == [
        {"exception_code": "missing_current_price", "row_count": 1},
        {"exception_code": "negative_settled_quantity", "row_count": 1},
    ]


def test_hidden_current_override_changes_quantity_location_and_date(tmp_path):
    """Current non-void overrides must apply before quantity validation and local date derivation."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    settled, _, _, _ = load_outputs(output_dir)
    row = next(row for row in settled if row["order_id"] == "H100" and row["fulfillment_id"] == "F2")
    assert row["ship_from_location"] == "LOC_P"
    assert row["local_service_date"] == "2026-03-11"
    assert row["settled_quantity_each"] == "4.000"


def test_hidden_sku_alias_settles_component_sku_to_order_sku(tmp_path):
    """SKU aliases must settle and aggregate component fulfillments under the documented settlement SKU."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    settled, _, _, _ = load_outputs(output_dir)
    row = next(row for row in settled if row["order_id"] == "H500" and row["fulfillment_id"] == "F8")
    assert row["sku"] == "SKU-SET"
    assert row["settled_quantity_each"] == "1.250"
    assert row["gross_amount"] == "10.63"


def test_hidden_allocation_basis_can_be_equal_or_gross(tmp_path):
    """Discount and adjustment allocation must use each order line's declared basis."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    settled, _, _, _ = load_outputs(output_dir)
    rows = [row for row in settled if row["order_id"] == "H500"]
    assert [row["fulfillment_id"] for row in rows] == ["F8", "F9"]
    assert [row["discount_amount"] for row in rows] == ["-0.02", "-0.01"]
    assert [row["adjustment_amount"] for row in rows] == ["0.03", "0.02"]


def test_hidden_lineage_tracks_duplicate_grain_before_aggregation(tmp_path):
    """Lineage must retain individual selected events even when settled rows aggregate."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    settled, _, _, lineage = load_outputs(output_dir)
    aggregate = next(row for row in settled if row["order_id"] == "H500" and row["fulfillment_id"] == "F8")
    rows = [
        row for row in lineage
        if row["row_type"] == "settled" and row["settled_key"] == aggregate["order_id"] + "|" + aggregate["line_id"] + "|" + aggregate["fulfillment_id"] + "|" + aggregate["sku"] + "|" + aggregate["ship_from_location"] + "|" + aggregate["local_service_date"]
    ]
    assert [row["event_key"] for row in rows] == ["H-E10", "H-E8"]
    assert [row["normalized_quantity_each"] for row in rows] == ["0.500", "0.750"]
    assert aggregate["settled_quantity_each"] == "1.250"


def test_hidden_lineage_records_current_override_source(tmp_path):
    """Lineage must name the current non-void override that changed the settled row."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    _, _, _, lineage = load_outputs(output_dir)
    row = next(row for row in lineage if row["event_key"] == "H-E2")
    assert row["applied_override_source_row_ids"] == "HOV002"
    assert row["ship_from_location"] == "LOC_P"
    assert row["local_service_date"] == "2026-03-11"


def test_hidden_lineage_records_price_tie_source_row(tmp_path):
    """Lineage must carry the price source selected after event-time tie-breaking."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    _, _, _, lineage = load_outputs(output_dir)
    row = next(row for row in lineage if row["event_key"] == "H-E3")
    assert row["selected_source_row_id"] == "H003B"
    assert row["price_source_row_id"] == "P-LAMBDA-003"
    assert row["pre_allocation_gross_amount"] == "29.20"


def test_hidden_lineage_exception_rows_keep_known_context(tmp_path):
    """Exception lineage rows must keep selected source and known settlement context."""
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    output_dir = tmp_path / "hidden_output"
    run_pipeline(input_dir, output_dir)
    _, _, _, lineage = load_outputs(output_dir)
    row = next(row for row in lineage if row["event_key"] == "H-E5")
    assert row["row_type"] == "exception"
    assert row["status"] == "missing_current_price"
    assert row["selected_source_row_id"] == "H005"
    assert row["settlement_sku"] == "SKU-MU"
    assert row["detail"] == "no price for SKU-MU USD at 2026-03-12T02:00:00Z"


def test_rules_helper_parse_dt_returns_timezone_aware_datetime():
    """The public timestamp parser must expose the documented API and preserve UTC."""
    rules = rules_module()
    parsed = rules.parse_dt("2026-01-02T03:04:05Z")
    assert parsed.isoformat() == "2026-01-02T03:04:05+00:00"


def test_rules_helper_current_record_uses_full_rank_tuple():
    """The public helper must select current records by effective_at, sequence, then source row."""
    rules = rules_module()
    rows = [
        {"event_key": "K1", "effective_at": "2026-01-01T00:00:00Z", "sequence_id": "7", "source_row_id": "R7A"},
        {"event_key": "K1", "effective_at": "2026-01-01T00:00:00Z", "sequence_id": "7", "source_row_id": "R7B"},
        {"event_key": "K1", "effective_at": "2025-12-31T23:59:00Z", "sequence_id": "9", "source_row_id": "R9A"},
    ]
    selected = rules.current_record(rows, lambda row: row["event_key"])
    assert [row["source_row_id"] for row in selected] == ["R7B"]


def test_rules_helper_selected_price_respects_event_time_and_source_tie():
    """The public price helper must ignore future prices and break same-version ties."""
    rules = rules_module()
    price_rows = {
        ("SKU-X", "USD"): [
            {"effective_at": "2026-01-01T00:00:00Z", "sequence_id": "1", "source_row_id": "PX1", "unit_price": "1.00"},
            {"effective_at": "2026-01-02T00:00:00Z", "sequence_id": "2", "source_row_id": "PX2A", "unit_price": "2.00"},
            {"effective_at": "2026-01-02T00:00:00Z", "sequence_id": "2", "source_row_id": "PX2B", "unit_price": "2.50"},
            {"effective_at": "2026-01-03T00:00:00Z", "sequence_id": "9", "source_row_id": "PX9", "unit_price": "9.99"},
        ]
    }
    price = rules.selected_price(
        price_rows,
        "SKU-X",
        "USD",
        rules.parse_dt("2026-01-02T12:00:00Z"),
    )
    assert price["source_row_id"] == "PX2B"
    assert price["unit_price"] == "2.50"


def test_rules_helper_allocation_handles_signed_ties_and_gross_basis():
    """The public allocation helper must honor basis choices and signed residual ties."""
    rules = rules_module()
    rows = [
        {
            "order_id": "T1",
            "line_id": "L1",
            "fulfillment_id": "F1",
            "sku": "SKU-X",
            "ship_from_location": "LOC_A",
            "local_service_date": "2026-01-01",
            "_quantity": Decimal("1"),
            "_gross": Decimal("1.00"),
        },
        {
            "order_id": "T1",
            "line_id": "L1",
            "fulfillment_id": "F2",
            "sku": "SKU-X",
            "ship_from_location": "LOC_A",
            "local_service_date": "2026-01-01",
            "_quantity": Decimal("1"),
            "_gross": Decimal("3.00"),
        },
    ]
    assert rules.allocate_cents("-0.03", rows, "equal") == [-2, -1]
    assert rules.allocate_cents("0.05", rows, "gross") == [1, 4]


def test_rules_helper_build_outputs_matches_hidden_oracle():
    """The public build_outputs helper must generalize, not just the CLI wrapper."""
    rules = rules_module()
    input_dir = TEST_ROOT / "hidden_batches" / "adversarial_batch"
    assert rules.build_outputs(input_dir) == expected_outputs(input_dir)[:3]


def test_rules_helper_current_void_event_suppresses_older_nonvoid(tmp_path):
    """A current void fulfillment record must not fall back to an older non-void version."""
    rules = rules_module()
    batch = tmp_path / "void_current"
    write_minimal_batch(
        batch,
        orders=[{"order_id": "T100", "line_id": "L1", "sku": "SKU-X", "currency": "USD", "total_discount": "0.00", "total_adjustment": "0.00", "discount_basis": "quantity", "adjustment_basis": "quantity"}],
        events=[
            {"event_key": "EV1", "source_row_id": "R1", "order_id": "T100", "line_id": "L1", "fulfillment_id": "F1", "sku": "SKU-X", "quantity": "2", "uom": "EACH", "ship_from_location": "LOC_A", "event_at": "2026-01-02T00:00:00Z", "effective_at": "2026-01-02T00:10:00Z", "ingested_at": "2026-01-02T00:11:00Z", "sequence_id": "1", "is_void": "false"},
            {"event_key": "EV1", "source_row_id": "R2", "order_id": "T100", "line_id": "L1", "fulfillment_id": "F1", "sku": "SKU-X", "quantity": "2", "uom": "EACH", "ship_from_location": "LOC_A", "event_at": "2026-01-02T00:00:00Z", "effective_at": "2026-01-02T00:20:00Z", "ingested_at": "2026-01-02T00:21:00Z", "sequence_id": "2", "is_void": "true"},
        ],
    )
    settled, exceptions, summary = rules.build_outputs(batch)
    assert settled == []
    assert exceptions == []
    assert summary["settled_row_count"] == 0


def test_rules_helper_current_void_override_does_not_apply_older_override(tmp_path):
    """A void current override should remove that override key instead of applying an older row."""
    rules = rules_module()
    batch = tmp_path / "void_override"
    write_minimal_batch(
        batch,
        orders=[{"order_id": "T200", "line_id": "L1", "sku": "SKU-X", "currency": "USD", "total_discount": "0.00", "total_adjustment": "0.00", "discount_basis": "quantity", "adjustment_basis": "quantity"}],
        events=[{"event_key": "EV2", "source_row_id": "R1", "order_id": "T200", "line_id": "L1", "fulfillment_id": "F1", "sku": "SKU-X", "quantity": "2", "uom": "EACH", "ship_from_location": "LOC_A", "event_at": "2026-01-02T00:00:00Z", "effective_at": "2026-01-02T00:10:00Z", "ingested_at": "2026-01-02T00:11:00Z", "sequence_id": "1", "is_void": "false"}],
        overrides=[
            {"override_key": "OV1", "source_row_id": "O1", "event_key": "EV2", "quantity_delta": "5", "uom": "EACH", "ship_from_location": "", "event_at": "", "effective_at": "2026-01-02T00:15:00Z", "sequence_id": "1", "is_void": "false"},
            {"override_key": "OV1", "source_row_id": "O2", "event_key": "EV2", "quantity_delta": "5", "uom": "EACH", "ship_from_location": "", "event_at": "", "effective_at": "2026-01-02T00:25:00Z", "sequence_id": "2", "is_void": "true"},
        ],
    )
    settled, _, _ = rules.build_outputs(batch)
    assert settled[0]["settled_quantity_each"] == "2.000"


def test_rules_helper_override_missing_conversion_uses_override_uom_detail(tmp_path):
    """Override quantity deltas must use conversion checks and precise exception details."""
    rules = rules_module()
    batch = tmp_path / "bad_override_uom"
    write_minimal_batch(
        batch,
        orders=[{"order_id": "T300", "line_id": "L1", "sku": "SKU-X", "currency": "USD", "total_discount": "0.00", "total_adjustment": "0.00", "discount_basis": "quantity", "adjustment_basis": "quantity"}],
        events=[{"event_key": "EV3", "source_row_id": "R1", "order_id": "T300", "line_id": "L1", "fulfillment_id": "F1", "sku": "SKU-X", "quantity": "2", "uom": "EACH", "ship_from_location": "LOC_A", "event_at": "2026-01-02T00:00:00Z", "effective_at": "2026-01-02T00:10:00Z", "ingested_at": "2026-01-02T00:11:00Z", "sequence_id": "1", "is_void": "false"}],
        overrides=[{"override_key": "OV2", "source_row_id": "O1", "event_key": "EV3", "quantity_delta": "1", "uom": "PACK", "ship_from_location": "", "event_at": "", "effective_at": "2026-01-02T00:25:00Z", "sequence_id": "1", "is_void": "false"}],
    )
    settled, exceptions, _ = rules.build_outputs(batch)
    assert settled == []
    assert exceptions == [
        {
            "exception_code": "missing_conversion",
            "order_id": "T300",
            "line_id": "L1",
            "fulfillment_id": "F1",
            "source_row_id": "R1",
            "detail": "no conversion for SKU-X PACK",
        }
    ]


def test_rules_helper_sku_mismatch_precedes_missing_conversion(tmp_path):
    """Unaliased SKU mismatches must route before conversion or price checks."""
    rules = rules_module()
    batch = tmp_path / "sku_precedence"
    write_minimal_batch(
        batch,
        orders=[{"order_id": "T400", "line_id": "L1", "sku": "SKU-X", "currency": "USD", "total_discount": "0.00", "total_adjustment": "0.00", "discount_basis": "quantity", "adjustment_basis": "quantity"}],
        events=[{"event_key": "EV4", "source_row_id": "R1", "order_id": "T400", "line_id": "L1", "fulfillment_id": "F1", "sku": "SKU-Y", "quantity": "2", "uom": "PACK", "ship_from_location": "LOC_A", "event_at": "2026-01-02T00:00:00Z", "effective_at": "2026-01-02T00:10:00Z", "ingested_at": "2026-01-02T00:11:00Z", "sequence_id": "1", "is_void": "false"}],
    )
    _, exceptions, _ = rules.build_outputs(batch)
    assert exceptions[0]["exception_code"] == "sku_mismatch"
    assert exceptions[0]["detail"] == "event sku does not match order line"


def test_rules_helper_price_lookup_returns_none_when_only_future_price_exists():
    """Future prices must not satisfy the current price lookup."""
    rules = rules_module()
    price_rows = {
        ("SKU-FUT", "USD"): [
            {"effective_at": "2026-02-01T00:00:00Z", "sequence_id": "1", "source_row_id": "PF1", "unit_price": "4.00"}
        ]
    }
    assert rules.selected_price(
        price_rows,
        "SKU-FUT",
        "USD",
        rules.parse_dt("2026-01-31T23:59:59Z"),
    ) is None
