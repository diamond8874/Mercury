"""
engine.py — Unified AI Cleaning Engine
=======================================
Single canonical cleaning engine used by both /api/process and the background processor.
Provides:
  - Strict Pydantic-based typed operation execution & NL fallback
  - Explicit KEEP semantics (zero mutation, zero implicit imputation)
  - Full before/after quality metrics (nulls, duplicates, dtypes, affected rows)
  - Detailed, structured audit logging of every operation
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple, List, Optional

from services.cleaning.intent_parser import build_cleaning_plan
from services.cleaning.validator import validate_plan
from services.cleaning.executor import execute_plan
from services.cleaning.audit import make_operation_log, make_dataset_summary
from services.cleaning.schema import (
    parse_typed_operation,
    validate_operation_against_dataframe,
    BaseOperation
)


def run_cleaning_engine(df: pd.DataFrame, actions: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes the complete data cleaning pipeline on a DataFrame based on column actions.
    Used identically by /api/process and background workers.

    Args:
        df: Input pandas DataFrame (will not mutate caller's original df if passed as copy)
        actions: Dict mapping column_name -> {
            "action": "keep" | "drop" | "transform",
            "reason": str,
            "transformation": Optional[str],
            "operations": Optional[List[dict]] # Typed Pydantic operations
        }

    Returns:
        Dict containing:
            "df": cleaned pd.DataFrame,
            "audit_log": list of per-operation audit entries,
            "quality_metrics": before/after comparison dict,
            "stats": backward-compatible stats dict,
            "transformations_applied": list of human-readable operation summaries,
            "columns_dropped": list of dropped columns,
            "warnings": list of warnings,
            "errors": list of errors
    """
    df = df.copy()
    df.columns = df.columns.str.strip()

    # 1. Initial Quality Metrics Snapshot
    initial_shape = df.shape
    initial_nulls = {c: int(df[c].isnull().sum()) for c in df.columns}
    initial_duplicates = int(df.duplicated().sum())
    initial_dtypes = {c: str(df[c].dtype) for c in df.columns}

    audit_log: List[Dict[str, Any]] = []
    transform_messages: List[str] = []
    all_warnings: List[str] = []
    all_errors: List[str] = []

    columns_to_drop: List[str] = []
    columns_to_keep: List[str] = []
    columns_modified: List[str] = []

    # 2. Iterate through approved column actions
    for col, col_data in actions.items():
        action = col_data.get("action", "keep")
        trans = col_data.get("transformation")
        typed_ops = col_data.get("operations")

        # Fuzzy match column name in case of casing differences
        target_col = col
        if col not in df.columns:
            matched = [c for c in df.columns if c.lower() == str(col).lower()]
            if matched:
                target_col = matched[0]
            else:
                all_warnings.append(f"Column '{col}' not found in dataset. Skipped.")
                continue

        # Case A: Drop column
        if action == "drop":
            columns_to_drop.append(target_col)
            audit_log.append(make_operation_log(
                column=target_col,
                operation="drop_column",
                parameters={},
                rows_before=len(df),
                rows_after=len(df),
                null_before=initial_nulls.get(target_col, 0),
                null_after=0,
                status="success",
                message=f"Scheduled drop for column '{target_col}'."
            ))
            continue

        # Case B: Keep column (STRICT NO-OP: do NOT mutate, do NOT impute)
        if action == "keep":
            columns_to_keep.append(target_col)
            audit_log.append(make_operation_log(
                column=target_col,
                operation="keep_column",
                parameters={},
                rows_before=len(df),
                rows_after=len(df),
                null_before=int(df[target_col].isnull().sum()) if target_col in df.columns else 0,
                null_after=int(df[target_col].isnull().sum()) if target_col in df.columns else 0,
                status="success",
                message=f"Kept column '{target_col}' unchanged without implicit modification or imputation."
            ))
            continue

        # Case C: Transform column
        if action == "transform":
            columns_to_keep.append(target_col)
            plan = []

            # Check for typed Pydantic operations first
            if typed_ops and isinstance(typed_ops, list):
                for op_item in typed_ops:
                    parsed_op = parse_typed_operation(op_item, default_column=target_col)
                    if parsed_op:
                        if not getattr(parsed_op, "column", None):
                            parsed_op.column = target_col
                        # Validate against real DataFrame
                        is_valid, err = validate_operation_against_dataframe(parsed_op, df)
                        if is_valid:
                            plan.append(parsed_op.to_plan_dict())
                        else:
                            all_warnings.append(f"Validation failed for operation '{parsed_op.operation}' on '{target_col}': {err}")
                    else:
                        all_warnings.append(f"Invalid operation schema in '{op_item}'.")

            # Fallback to intent parser if no typed operations provided
            if not plan and trans:
                raw_trans = str(trans).strip()
                if raw_trans:
                    parsed_plan = build_cleaning_plan(target_col, raw_trans, df)
                    val_results = validate_plan(parsed_plan, df)
                    errs = [r["message"] for r in val_results if r["status"] == "error"]
                    if errs:
                        err_msg = f"Validation failed for '{target_col}': " + " | ".join(errs)
                        all_errors.append(err_msg)
                        audit_log.append(make_operation_log(
                            column=target_col,
                            operation="validation_error",
                            parameters={"raw_trans": raw_trans},
                            rows_before=len(df),
                            rows_after=len(df),
                            null_before=int(df[target_col].isnull().sum()) if target_col in df.columns else 0,
                            null_after=int(df[target_col].isnull().sum()) if target_col in df.columns else 0,
                            status="error",
                            error=err_msg,
                            message=err_msg
                        ))
                        continue
                    plan = parsed_plan

            if plan:
                exec_res = execute_plan(plan, df)
                df = exec_res["df"]
                audit_log.extend(exec_res.get("audit_log", []))
                if exec_res.get("warnings"):
                    all_warnings.extend(exec_res["warnings"])
                if exec_res.get("errors"):
                    all_errors.extend(exec_res["errors"])
                columns_modified.append(target_col)
                msgs = [item["message"] for item in exec_res["audit_log"] if item.get("message")]
                if msgs:
                    transform_messages.append(" | ".join(msgs))
            else:
                msg = f"No executable operations found for column '{target_col}'"
                transform_messages.append(msg)

    # 3. Apply Column Drops
    valid_drops = [c for c in columns_to_drop if c in df.columns]
    if valid_drops:
        df = df.drop(columns=valid_drops)

    # 4. Final Quality Metrics Snapshot
    final_shape = df.shape
    final_nulls = {c: int(df[c].isnull().sum()) for c in df.columns}
    final_duplicates = int(df.duplicated().sum())
    final_dtypes = {c: str(df[c].dtype) for c in df.columns}

    # 5. Quality Metrics Comparison
    total_null_before = sum(initial_nulls.values())
    total_null_after = sum(final_nulls.values())
    nulls_resolved = max(0, total_null_before - total_null_after)
    duplicate_rows_removed = max(0, initial_duplicates - final_duplicates)
    rows_affected = abs(initial_shape[0] - final_shape[0])

    dtype_changes = {}
    for c in df.columns:
        if c in initial_dtypes and initial_dtypes[c] != final_dtypes[c]:
            dtype_changes[c] = {"before": initial_dtypes[c], "after": final_dtypes[c]}

    quality_metrics = {
        "initial_rows": initial_shape[0],
        "final_rows": final_shape[0],
        "rows_affected": rows_affected,
        "initial_cols": initial_shape[1],
        "final_cols": final_shape[1],
        "columns_dropped": valid_drops,
        "columns_added": [c for c in df.columns if c not in initial_dtypes],
        "null_before": total_null_before,
        "null_after": total_null_after,
        "nulls_resolved": nulls_resolved,
        "null_per_column_before": initial_nulls,
        "null_per_column_after": final_nulls,
        "duplicate_rows_before": initial_duplicates,
        "duplicate_rows_after": final_duplicates,
        "duplicate_rows_removed": duplicate_rows_removed,
        "dtype_changes": dtype_changes,
    }

    # Backward-compatible stats dict expected by existing frontend / download routes
    stats = {
        "initial_rows": initial_shape[0],
        "initial_cols": initial_shape[1],
        "final_rows": final_shape[0],
        "final_cols": final_shape[1],
        "dropped_columns": valid_drops,
        "transformations_applied": transform_messages,
        "null_before": total_null_before,
        "null_after": total_null_after,
        "duplicate_before": initial_duplicates,
        "duplicate_after": final_duplicates,
        "quality_metrics": quality_metrics
    }

    return {
        "df": df,
        "audit_log": audit_log,
        "quality_metrics": quality_metrics,
        "stats": stats,
        "transformations_applied": transform_messages,
        "columns_dropped": valid_drops,
        "warnings": all_warnings,
        "errors": all_errors
    }
