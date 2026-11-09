from __future__ import annotations

from typing import Any

import sparse_contract_ext


def merge_lane_coalesce(row: list[int], col: list[int], val: list[float], rows: int, cols: int) -> dict[str, Any]:
    """Sort-only coalesce via native extension (duplicate indices remain)."""
    return sparse_contract_ext.coalesce_coo(row, col, val, rows, cols)
