The settlement export in `/app` is not reliable yet. Repair `/app/settlement_pipeline.py` and the helper code in `/app/settlement_engine/rules.py` so they implement the business contract in `/app/spec/settlement_contract.md`, then run the export for the batch in `/app/data/current_batch`.

Downstream jobs import `/app/settlement_engine/rules.py` directly, so keep the helper API described in `/app/spec/settlement_contract.md` compatible with the CLI behavior instead of only making the visible files look right.

The pipeline must keep working for another batch with the same file names and columns when called like this:

```bash
python3 /app/settlement_pipeline.py --input-dir /app/data/current_batch --output-dir /app/output
```

Create these files:

`/app/output/settled_order_lines.csv`

Columns, in order: `order_id`, `line_id`, `fulfillment_id`, `sku`, `ship_from_location`, `local_service_date`, `currency`, `settled_quantity_each`, `unit_price`, `gross_amount`, `discount_amount`, `adjustment_amount`, `net_amount`.

`/app/output/settlement_exceptions.csv`

Columns, in order: `exception_code`, `order_id`, `line_id`, `fulfillment_id`, `source_row_id`, `detail`.

`/app/output/reconciliation_summary.json`

Use the exact JSON shape described in `/app/spec/settlement_contract.md`. Counts must be numbers. Money and quantity values must be canonical decimal strings, not floats.

`/app/output/settlement_lineage.csv`

Use the exact columns, row semantics, ordering, and digest relationship described in `/app/spec/settlement_contract.md`.

The finished result should be based on the documented settlement rules, not on hardcoded rows for the visible batch.
