"""
audit.py — Structured Audit Log for Cleaning Operations
=========================================================
Generates per-operation and dataset-level audit entries.
Does NOT import pandas directly to keep it lightweight; callers pass in stats.
"""

import logging
import time
from typing import Any


def make_operation_log(
    column: str,
    operation: str,
    parameters: dict,
    rows_before: int,
    rows_after: int,
    null_before: int,
    null_after: int,
    status: str = "success",
    message: str = "",
    error: str = None,
    execution_time_ms: float = 0.0,
) -> dict:
    """
    Build a structured audit log entry for a single operation.

    Returns:
        dict with full audit information.
    """
    entry = {
        "column": column,
        "operation": operation,
        "parameters": parameters,
        "rows_before": rows_before,
        "rows_after": rows_after,
        "rows_affected": abs(rows_before - rows_after) if operation != "rename_column" else 0,
        "null_before": null_before,
        "null_after": null_after,
        "nulls_filled": max(0, null_before - null_after),
        "status": status,
        "message": message,
        "execution_time_ms": round(execution_time_ms, 2),
    }
    if error:
        entry["error"] = error
    return entry


def make_dataset_summary(
    initial_shape: tuple,
    final_shape: tuple,
    initial_nulls: dict,
    final_nulls: dict,
    initial_dtypes: dict,
    final_dtypes: dict,
    initial_duplicates: int,
    final_duplicates: int,
    operations_performed: list,
    columns_removed: list,
    columns_modified: list,
    warnings: list,
    errors: list,
) -> dict:
    """
    Build a dataset-level before/after summary for the cleaning session.

    Returns:
        dict with full summary.
    """
    dtype_changes = {}
    all_cols = set(list(initial_dtypes.keys()) + list(final_dtypes.keys()))
    for col in all_cols:
        before_dt = initial_dtypes.get(col)
        after_dt = final_dtypes.get(col)
        if before_dt != after_dt and after_dt is not None:
            dtype_changes[col] = {"before": before_dt, "after": after_dt}

    total_nulls_before = sum(initial_nulls.values())
    total_nulls_after = sum(final_nulls.values())

    return {
        "initial_rows": initial_shape[0],
        "initial_cols": initial_shape[1],
        "final_rows": final_shape[0],
        "final_cols": final_shape[1],
        "rows_removed": initial_shape[0] - final_shape[0],
        "columns_removed": columns_removed,
        "columns_modified": columns_modified,
        "null_before": total_nulls_before,
        "null_after": total_nulls_after,
        "null_per_column_before": initial_nulls,
        "null_per_column_after": final_nulls,
        "duplicate_before": initial_duplicates,
        "duplicate_after": final_duplicates,
        "dtype_changes": dtype_changes,
        "operations_performed": operations_performed,
        "warnings": warnings,
        "errors": errors,
    }


class OperationTimer:
    """Context manager for timing individual operations."""

    def __init__(self):
        self.elapsed_ms = 0.0
        self._start = None

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = (time.perf_counter() - self._start) * 1000
