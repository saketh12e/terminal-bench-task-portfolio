#!/usr/bin/env python3
import argparse
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
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
        rank = (row.get("effective_at", ""), row.get("source_row_id", ""))
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, row)
    return [row for _, row in selected.values()]


def selected_price(price_rows, sku, currency, event_at):
    candidates = price_rows.get((sku, currency), [])
    if not candidates:
        return None
    return sorted(candidates, key=lambda row: row["effective_at"])[-1]


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


def exception_for(code, event, detail):
    return {
        "exception_code": code,
        "order_id": event["order_id"],
        "line_id": event["line_id"],
        "fulfillment_id": event["fulfillment_id"],
        "source_row_id": event["source_row_id"],
        "detail": detail,
    }


def allocation_weight(row, basis):
    if basis == "gross":
        return row["_gross"]
    if basis == "equal":
        return Decimal("1")
    return row["_quantity"]


def allocate_cents(total_money, rows, basis):
    if not rows:
        return []
    weights = [allocation_weight(row, basis) for row in rows]
    total_weight = sum(weights)
    if total_weight == 0:
        return [0 for _ in rows]
    total = Decimal(total_money) * Decimal(100)
    return [
        int((total * weight / total_weight).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        for weight in weights
    ]


def cents_to_money(cents):
    return Decimal(cents) / Decimal(100)


def lineage_sha256(rows):
    return hashlib.sha256(csv_payload(LINEAGE_FIELDS, rows).encode()).hexdigest()


def build_outputs(input_dir):
    settled, exceptions, summary, _ = build_package(input_dir)
    return settled, exceptions, summary


def build_package(input_dir):
    orders = {
        (row["order_id"], row["line_id"]): row
        for row in read_csv(input_dir / "order_lines.csv")
    }
    conversions = {
        (row["sku"], row["uom"]): Decimal(row["each_per_unit"])
        for row in read_csv(input_dir / "packaging_conversions.csv")
    }
    prices = defaultdict(list)
    for row in read_csv(input_dir / "price_history.csv"):
        prices[(row["sku"], row["currency"])].append(row)

    settled_by_key = {}
    exceptions = []
    lineage = []

    for event in current_record(read_csv(input_dir / "fulfillment_events.csv"), lambda row: row["event_key"]):
        if parse_bool(event["is_void"]):
            continue
        order = orders.get((event["order_id"], event["line_id"]))
        if order is None:
            exceptions.append(exception_for("unmatched_order_line", event, "order line not found"))
            continue

        factor = conversions.get((event["sku"], event["uom"]))
        price = selected_price(prices, event["sku"], order["currency"], parse_dt(event["event_at"]))
        if factor is None:
            exceptions.append(
                exception_for(
                    "missing_conversion",
                    event,
                    f"no conversion for {event['sku']} {event['uom']}",
                )
            )
            continue
        if price is None:
            exceptions.append(
                exception_for(
                    "missing_current_price",
                    event,
                    f"no price for {event['sku']} {order['currency']} at {event['event_at']}",
                )
            )
            continue

        quantity = (Decimal(event["quantity"]) * factor).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
        if quantity <= 0:
            exceptions.append(
                exception_for("negative_settled_quantity", event, "normalized quantity is not positive")
            )
            continue

        unit_price = Decimal(price["unit_price"]).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        gross = (quantity * unit_price).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        local_service_date = event["event_at"][:10]
        key = (
            event["order_id"],
            event["line_id"],
            event["fulfillment_id"],
            event["sku"],
            event["ship_from_location"],
            local_service_date,
        )
        if key not in settled_by_key:
            settled_by_key[key] = {
                "order_id": event["order_id"],
                "line_id": event["line_id"],
                "fulfillment_id": event["fulfillment_id"],
                "sku": event["sku"],
                "ship_from_location": event["ship_from_location"],
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
                "settlement_sku": event["sku"],
                "ship_from_location": event["ship_from_location"],
                "local_service_date": local_service_date,
                "applied_override_source_row_ids": "",
                "price_source_row_id": price["source_row_id"],
                "normalized_quantity_each": quantity_str(quantity),
                "pre_allocation_gross_amount": money_str(gross),
                "detail": "",
            }
        )

    settled = sorted(settled_by_key.values(), key=settled_sort_key)
    by_line = defaultdict(list)
    for row in settled:
        by_line[(row["order_id"], row["line_id"])].append(row)
    for key, rows in by_line.items():
        order = orders[key]
        discount_cents = allocate_cents(order["total_discount"], rows, order["discount_basis"])
        adjustment_cents = allocate_cents(order["total_adjustment"], rows, order["adjustment_basis"])
        for row, discount, adjustment in zip(rows, discount_cents, adjustment_cents):
            gross = row["_gross"].quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
            row["settled_quantity_each"] = quantity_str(row["_quantity"])
            row["gross_amount"] = money_str(gross)
            row["discount_amount"] = money_str(cents_to_money(discount))
            row["adjustment_amount"] = money_str(cents_to_money(adjustment))
            row["net_amount"] = money_str(gross + cents_to_money(discount) + cents_to_money(adjustment))

    output_settled = [{field: row[field] for field in SETTLED_FIELDS} for row in settled]
    output_exceptions = sorted(exceptions, key=exception_sort_key)
    output_lineage = sorted(lineage, key=lineage_sort_key)

    totals = defaultdict(lambda: defaultdict(Decimal))
    for row in output_settled:
        for field in ["gross_amount", "discount_amount", "adjustment_amount", "net_amount"]:
            totals[row["currency"]][field] += Decimal(row[field])

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
            for currency, values in sorted(totals.items())
        ],
        "exception_counts": [
            {"exception_code": code, "row_count": count}
            for code, count in sorted(Counter(row["exception_code"] for row in output_exceptions).items())
        ],
    }
    return output_settled, output_exceptions, summary, output_lineage


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="/app/data/current_batch")
    parser.add_argument("--output-dir", default="/app/output")
    args = parser.parse_args()
    settled, exceptions, summary, lineage = build_package(Path(args.input_dir))
    output_dir = Path(args.output_dir)
    write_csv(output_dir / "settled_order_lines.csv", SETTLED_FIELDS, settled)
    write_csv(output_dir / "settlement_exceptions.csv", EXCEPTION_FIELDS, exceptions)
    write_csv(output_dir / "settlement_lineage.csv", LINEAGE_FIELDS, lineage)
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "reconciliation_summary.json", "w") as fh:
        json.dump(summary, fh, indent=2)
        fh.write("\n")


if __name__ == "__main__":
    main()
