from __future__ import annotations


def parity_nnz_count(catalog_row: list[int], grad_sparse: list[float]) -> int:
    """Broken: reports raw catalog COO length, not coalesced logical nnz."""
    return len(catalog_row)
