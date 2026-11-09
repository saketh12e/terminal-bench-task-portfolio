Settlement contract

The pipeline reads a batch directory containing `order_lines.csv`, `fulfillment_events.csv`, `fulfillment_overrides.csv`, `sku_aliases.csv`, `packaging_conversions.csv`, `locations.csv`, and `price_history.csv`. It writes the three output files requested by the task instruction.

Input files

`order_lines.csv`

Columns: `order_id`, `line_id`, `sku`, `currency`, `total_discount`, `total_adjustment`, `discount_basis`, `adjustment_basis`.

`fulfillment_events.csv`

Columns: `event_key`, `source_row_id`, `order_id`, `line_id`, `fulfillment_id`, `sku`, `quantity`, `uom`, `ship_from_location`, `event_at`, `effective_at`, `ingested_at`, `sequence_id`, `is_void`.

`fulfillment_overrides.csv`

Columns: `override_key`, `source_row_id`, `event_key`, `quantity_delta`, `uom`, `ship_from_location`, `event_at`, `effective_at`, `sequence_id`, `is_void`.

`sku_aliases.csv`

Columns: `order_sku`, `event_sku`, `settlement_sku`, `quantity_multiplier`.

`packaging_conversions.csv`

Columns: `sku`, `uom`, `each_per_unit`.

`locations.csv`

Columns: `ship_from_location`, `utc_offset_minutes`.

`price_history.csv`

Columns: `sku`, `currency`, `unit_price`, `effective_at`, `sequence_id`, `source_row_id`.

Current records

Fulfillment events are versioned by `event_key`. Select one current event per `event_key` using the highest `effective_at`, then the highest numeric `sequence_id`, then the lexicographically largest `source_row_id`. If the selected current event has `is_void` equal to `true`, do not settle it and do not emit an exception for it.

Fulfillment overrides are versioned by `override_key`, but each override row targets an `event_key`. Select one current override per `override_key` using the same highest `effective_at`, highest numeric `sequence_id`, and lexicographically largest `source_row_id` rule. If the selected override has `is_void` equal to `true`, ignore that override. If more than one non-void selected override targets the same `event_key`, apply them in `override_key` sort order.

For unit prices, use rows from `price_history.csv` with the final settlement `sku` and order-line `currency` where `effective_at` is less than or equal to the final event `event_at`. Select the current price using the highest `effective_at`, then the highest numeric `sequence_id`, then the lexicographically largest `source_row_id`.

Canonical settlement grain and sort order

The settled output has one row per strict grain:

`order_id`, `line_id`, `fulfillment_id`, `sku`, `ship_from_location`, `local_service_date`.

Those columns are also the settled CSV sort key, in that order. The final settled sort key is guaranteed to be unique after aggregation. The same unique sort key is used to break any residual-cent allocation ties.

Apply non-void overrides after current fulfillment selection and before SKU aliasing, quantity validation, timezone lookup, and price selection. If `quantity_delta` is not blank, convert that delta using the selected event SKU and the override `uom`, then add it to the selected event's converted quantity. If override `ship_from_location` is not blank, replace the selected event's `ship_from_location`. If override `event_at` is not blank, replace the selected event's `event_at`.

Derive `local_service_date` only after current fulfillment selection and all non-void overrides have been applied. Parse the final `event_at` as UTC, add the final `ship_from_location` offset from `locations.csv`, then use the resulting local calendar date in `YYYY-MM-DD` format.

Quantity and money

Use Decimal arithmetic. Convert event quantities to eaches with `quantity * each_per_unit`. Convert override quantity deltas the same way, then add them to the event quantity before alias multiplication. The `EACH` unit is still read from `packaging_conversions.csv`. Canonical quantity strings have exactly 3 decimal places and are rounded with `ROUND_HALF_UP`.

If the selected event SKU differs from the order-line SKU, look for a row in `sku_aliases.csv` with matching `order_sku` and `event_sku`. If no alias row exists, route `sku_mismatch`. If an alias row exists, use its `settlement_sku` as the output `sku` and for price selection. Multiply the normalized each quantity by `quantity_multiplier` before quantity validation and gross calculation. If the selected event SKU already matches the order-line SKU, the output `sku` is the order-line SKU and the multiplier is `1`.

Canonical money strings have exactly 2 decimal places and are rounded with `ROUND_HALF_UP`. Outputs are compared as canonical decimal strings, so using floats internally is allowed only if the emitted strings still match the Decimal result exactly. A double-rounding error should fail.

For each settled row:

`gross_amount = settled_quantity_each * unit_price`, rounded to cents with `ROUND_HALF_UP`.

`net_amount = gross_amount + discount_amount + adjustment_amount`.

Discount and adjustment allocation

`total_discount` and `total_adjustment` live at the order-line level. Allocate each value across the settled rows for the same `order_id` and `line_id`. `discount_basis` controls the discount allocation basis and `adjustment_basis` controls the adjustment allocation basis. Each basis value is one of `quantity`, `gross`, or `equal`.

For `quantity`, use the row's normalized `settled_quantity_each` as the allocation weight. For `gross`, use the row's pre-allocation `gross_amount` as the weight. For `equal`, use weight `1` for every settled row in that order line.

For each allocation value:

1. Convert the order-line value to integer cents.
2. Compute each row's exact unrounded Decimal share in cents.
3. Floor each positive share toward zero and ceil each negative share toward zero.
4. Sum the base cents and compute the signed residual cents needed to reach the source total.
5. Distribute residual cents one at a time to rows with the largest absolute fractional remainders.
6. Break remainder ties by the unique settled output sort key.

This rule is intentional. Do not allocate by independent per-row half-up rounding.

Exception routing

Evaluate exceptions in this order. Emit at most one exception row for a selected, non-void fulfillment event.

1. `unmatched_order_line`: no matching `order_id`, `line_id` exists in `order_lines.csv`. Detail: `order line not found`.
2. `sku_mismatch`: the selected fulfillment event SKU differs from the order-line SKU. Detail: `event sku does not match order line`.
3. `missing_conversion`: no conversion row exists for the selected `sku`, `uom`. Detail: `no conversion for <sku> <uom>`.
4. `negative_settled_quantity`: the normalized each quantity is less than or equal to zero. Detail: `normalized quantity is not positive`.
5. `unresolved_timezone`: no location row exists for the selected `ship_from_location`. Detail: `no timezone offset for <ship_from_location>`.
6. `missing_current_price`: no price row exists for the final settlement `sku`, order-line `currency` with `effective_at` less than or equal to the final event's `event_at`. Detail: `no price for <sku> <currency> at <event_at>`.

Sort `settlement_exceptions.csv` by `exception_code`, `order_id`, `line_id`, `fulfillment_id`, `source_row_id`. This sort key is guaranteed to be unique for exception rows.

Output schemas

`settled_order_lines.csv`

Columns, in order: `order_id`, `line_id`, `fulfillment_id`, `sku`, `ship_from_location`, `local_service_date`, `currency`, `settled_quantity_each`, `unit_price`, `gross_amount`, `discount_amount`, `adjustment_amount`, `net_amount`.

`settlement_exceptions.csv`

Columns, in order: `exception_code`, `order_id`, `line_id`, `fulfillment_id`, `source_row_id`, `detail`.

`reconciliation_summary.json`

The top-level object has exactly these keys:

`settled_row_count`: integer count of settled rows.

`exception_row_count`: integer count of exception rows.

`lineage_row_count`: integer count of lineage rows.

`lineage_sha256`: lowercase SHA-256 hex digest of the exact `settlement_lineage.csv` bytes, including the header row and CSV line endings produced by `csv.DictWriter` with the documented column order.

`currency_totals`: array sorted by `currency`. Each object has exactly `currency`, `gross_amount`, `discount_amount`, `adjustment_amount`, and `net_amount`. Money totals are canonical 2 decimal strings.

`exception_counts`: array sorted by `exception_code`. Each object has exactly `exception_code` and `row_count`.

`settlement_lineage.csv`

Columns, in order: `row_type`, `status`, `order_id`, `line_id`, `fulfillment_id`, `event_key`, `selected_source_row_id`, `settled_key`, `settlement_sku`, `ship_from_location`, `local_service_date`, `applied_override_source_row_ids`, `price_source_row_id`, `normalized_quantity_each`, `pre_allocation_gross_amount`, `detail`.

Emit one lineage row for each selected, non-void fulfillment event that either settles or emits an exception. Do not emit lineage rows for current fulfillment events whose selected row is void.

For settled lineage rows, set `row_type` and `status` to `settled`. `selected_source_row_id` is the current fulfillment event source row. `settled_key` is `order_id|line_id|fulfillment_id|settlement_sku|ship_from_location|local_service_date` after all non-void overrides, aliasing, and timezone derivation. `applied_override_source_row_ids` is a semicolon-separated list of applied current override source rows in override application order, or blank. `price_source_row_id` is the selected price row. `normalized_quantity_each` is that event contribution before duplicate-grain aggregation, canonical to 3 decimals. `pre_allocation_gross_amount` is that event contribution before order-line discount and adjustment allocation, canonical to 2 decimals. `detail` is blank.

For exception lineage rows, set `row_type` to `exception`, `status` to the exception code, `selected_source_row_id` to the current fulfillment event source row, and `detail` to the exception detail. Fill `settlement_sku`, `ship_from_location`, and `applied_override_source_row_ids` with the values known at the point the exception is routed. Leave `settled_key`, `local_service_date`, `price_source_row_id`, `normalized_quantity_each`, and `pre_allocation_gross_amount` blank.

Sort `settlement_lineage.csv` by `row_type`, `status`, `order_id`, `line_id`, `fulfillment_id`, `event_key`, `selected_source_row_id`. This sort key is guaranteed to be unique.

Helper API

Downstream checks import `/app/settlement_engine/rules.py`. Preserve these public call shapes while making their behavior follow the same settlement contract:

`parse_dt(value: str)`: return a timezone-aware datetime for an ISO UTC timestamp ending in `Z`.

`current_record(rows, key_func)`: group row dictionaries by `key_func(row)` and return a list containing the selected current row for each group.

`selected_price(price_rows, sku, currency, event_at)`: `price_rows` is a dictionary keyed by `(sku, currency)` and `event_at` is already parsed; return the selected price row or `None`.

`allocate_cents(total_money, rows, basis)`: return integer cents for the rows in input order. Rows may carry internal Decimal fields `_quantity` and `_gross` for the documented quantity and gross allocation bases.

`build_outputs(input_dir)`: read a batch directory and return `(settled_rows, exception_rows, reconciliation_summary)` without writing files.
