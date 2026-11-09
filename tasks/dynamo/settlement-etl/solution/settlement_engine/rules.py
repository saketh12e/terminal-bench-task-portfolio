#!/usr/bin/env python3
import argparse
import csv
import hashlib
import json
import io
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from pathlib import Path


QTY_QUANT = Decimal("0.001")
MONEY_QUANT = Decimal("0.01")

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


def read_csv(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, fields, rows):
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


def settled_key_text(row):
    return "|".join(
        [
            row["order_id"],
            row["line_id"],
            row["fulfillment_id"],
            row["sku"],
            row["ship_from_location"],
            row["local_service_date"],
        ]
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


def build_outputs(input_dir):
    settled, exceptions, summary, _ = build_package(input_dir)
    return settled, exceptions, summary


def build_package(input_dir):
    order_rows = read_csv(input_dir / "order_lines.csv")
    event_rows = read_csv(input_dir / "fulfillment_events.csv")
    override_rows = read_csv(input_dir / "fulfillment_overrides.csv")
    alias_rows = read_csv(input_dir / "sku_aliases.csv")
    conversion_rows = read_csv(input_dir / "packaging_conversions.csv")
    location_rows = read_csv(input_dir / "locations.csv")
    price_rows = read_csv(input_dir / "price_history.csv")

    orders = {(row["order_id"], row["line_id"]): row for row in order_rows}
    conversions = {
        (row["sku"], row["uom"]): Decimal(row["each_per_unit"])
        for row in conversion_rows
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
        for row in location_rows
    }
    prices = defaultdict(list)
    for row in price_rows:
        prices[(row["sku"], row["currency"])].append(row)

    exceptions = []
    lineage = []
    settled_by_key = {}

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

        row = settled_by_key[key]
        row["_quantity"] += quantity
        row["_gross"] += gross

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

    output_settled = []
    for row in settled:
        output_settled.append({field: row[field] for field in SETTLED_FIELDS})

    output_exceptions = sorted(exceptions, key=exception_sort_key)
    output_lineage = sorted(lineage, key=lineage_sort_key)

    currency_totals = defaultdict(lambda: defaultdict(Decimal))
    for row in output_settled:
        for field in [
            "gross_amount",
            "discount_amount",
            "adjustment_amount",
            "net_amount",
        ]:
            currency_totals[row["currency"]][field] += Decimal(row[field])

    summary = {
        "settled_row_count": len(output_settled),
        "exception_row_count": len(output_exceptions),
        "lineage_row_count": len(output_lineage),
        "lineage_sha256": lineage_sha256(output_lineage),
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
                Counter(row["exception_code"] for row in output_exceptions).items()
            )
        ],
    }
    return output_settled, output_exceptions, summary, output_lineage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="/app/data/current_batch")
    parser.add_argument("--output-dir", default="/app/output")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    settled, exceptions, summary, lineage = build_package(input_dir)
    write_csv(output_dir / "settled_order_lines.csv", SETTLED_FIELDS, settled)
    write_csv(output_dir / "settlement_exceptions.csv", EXCEPTION_FIELDS, exceptions)
    write_csv(output_dir / "settlement_lineage.csv", LINEAGE_FIELDS, lineage)
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "reconciliation_summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")


if __name__ == "__main__":
    main()
