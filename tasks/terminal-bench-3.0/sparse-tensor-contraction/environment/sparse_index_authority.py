from __future__ import annotations

from typing import Any


def authority_coalesce(row: list[int], col: list[int], val: list[float], rows: int, cols: int) -> dict[str, Any]:
    """Correct COO coalesce: lex sort plus value sum at duplicate (row,col)."""
    entries = list(zip(row, col, val))
    entries.sort(key=lambda t: (t[0], t[1]))
    merged: list[tuple[int, int, float]] = []
    for r, c, v in entries:
        if merged and merged[-1][0] == r and merged[-1][1] == c:
            pr, pc, pv = merged[-1]
            merged[-1] = (pr, pc, pv + v)
        else:
            merged.append((r, c, v))
    out_row = [m[0] for m in merged]
    out_col = [m[1] for m in merged]
    out_val = [m[2] for m in merged]
    return {"rows": rows, "cols": cols, "row": out_row, "col": out_col, "val": out_val}
