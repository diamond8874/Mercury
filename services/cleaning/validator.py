"""
validator.py — Pre-Execution Validation for Cleaning Plans
===========================================================
Validates a structured cleaning plan against the dataframe BEFORE any execution.
Returns a list of validation results; the caller decides whether to proceed.

No dataframe is modified here.
"""

import logging
import pandas as pd
from services.cleaning.operation_registry import OPERATIONS, get_operation


# Operations that require numeric dtype
_NUMERIC_ONLY_OPS = {
    "impute_mean", "impute_median", "impute_zero",
    "normalize_minmax", "standardize_zscore", "log_transform",
    "round_values", "clip_iqr", "drop_iqr_rows", "clip_percentile",
    "convert_unit", "handle_infinity", "derived_math",
    "parse_accounting_currency", "convert_percentage",
}

# Operations that require text/object dtype
_TEXT_ONLY_OPS = {
    "uppercase", "lowercase", "titlecase", "strip_whitespace",
    "remove_punctuation", "remove_html", "remove_stopwords",
    "string_length", "extract_digits", "extract_email", "extract_phone",
    "split_column", "replace_value_substring",
}


def validate_plan(plan: list, df: pd.DataFrame) -> list:
    """
    Validate a list of planned operations against the dataframe.

    Args:
        plan: list of dicts from intent_parser.build_cleaning_plan()
        df:   the current (unmodified) dataframe

    Returns:
        list of validation result dicts, one per planned operation.
        Each result has:
            {
                "index": int,
                "column": str,
                "operation": str,
                "status": "ok" | "warning" | "error",
                "error_type": str | None,
                "message": str
            }
    """
    results = []
    columns_to_be_dropped = set()   # Track ops that drop columns so conflicts can be detected

    for i, op_dict in enumerate(plan):
        col = op_dict.get("column", "")
        operation = op_dict.get("operation", "")
        parameters = op_dict.get("parameters", {})

        result = {
            "index": i,
            "column": col,
            "operation": operation,
            "status": "ok",
            "error_type": None,
            "message": f"Operation '{operation}' on '{col}' is valid.",
        }

        # ── Already flagged by parser ──────────────────────────────────────────
        if operation == "ambiguous_instruction":
            result["status"] = "error"
            result["error_type"] = "AmbiguousInstruction"
            result["message"] = op_dict.get("message", f"Ambiguous instruction for '{col}'. Please be more specific.")
            results.append(result)
            continue

        if operation == "unsupported":
            result["status"] = "error"
            result["error_type"] = "UnsupportedOperation"
            result["message"] = op_dict.get("message", f"Unsupported operation requested for '{col}'.")
            results.append(result)
            continue

        if operation == "ambiguous_column":
            result["status"] = "error"
            result["error_type"] = "AmbiguousColumn"
            candidates = op_dict.get("candidates", [])
            result["message"] = (
                f"Ambiguous column reference. Found multiple matches: {candidates}. "
                "Please specify the exact column name."
            )
            results.append(result)
            continue

        if operation == "keep_column":
            result["message"] = f"Column '{col}' is marked as unchanged. No modification will occur."
            results.append(result)
            continue

        # ── Dataset-scope operations ──────────────────────────────────────────
        op_def = get_operation(operation)
        if op_def and op_def.get("scope") == "dataset":
            if operation == "keep_only_columns":
                keep_cols = parameters.get("columns", [])
                missing = [c for c in keep_cols if c not in df.columns]
                if missing:
                    result["status"] = "warning"
                    result["error_type"] = "ColumnNotFound"
                    result["message"] = (
                        f"keep_only_columns: The following specified columns were not found "
                        f"in the dataset: {missing}. They will be ignored."
                    )
            elif operation in ("filter_rows", "remove_rows"):
                f_col = parameters.get("col", "")
                if f_col and f_col not in df.columns:
                    result["status"] = "error"
                    result["error_type"] = "ColumnNotFound"
                    result["message"] = f"Filter column '{f_col}' not found in dataset."
            results.append(result)
            continue

        # ── Column existence check ────────────────────────────────────────────
        if col and col not in df.columns:
            result["status"] = "error"
            result["error_type"] = "ColumnNotFound"
            result["message"] = f"Column '{col}' not found in dataset."
            results.append(result)
            continue

        # ── Conflict: column was already scheduled to be dropped ──────────────
        if col in columns_to_be_dropped and operation != "drop_column":
            result["status"] = "error"
            result["error_type"] = "ConflictingOperations"
            result["message"] = (
                f"Column '{col}' is scheduled to be dropped earlier in the plan, "
                f"but operation '{operation}' also targets it."
            )
            results.append(result)
            continue

        if operation == "drop_column":
            columns_to_be_dropped.add(col)

        # ── Dtype compatibility ───────────────────────────────────────────────
        if col in df.columns:
            is_numeric = pd.api.types.is_numeric_dtype(df[col])
            is_text = pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object

            if operation in _NUMERIC_ONLY_OPS and not is_numeric:
                # Allow if column CAN be coerced to numeric (e.g. "123" strings)
                try:
                    test = pd.to_numeric(df[col], errors='raise')
                    result["status"] = "warning"
                    result["message"] = (
                        f"Column '{col}' is dtype '{df[col].dtype}' but appears numeric. "
                        "Values will be coerced to numeric before the operation."
                    )
                except Exception:
                    result["status"] = "error"
                    result["error_type"] = "DtypeIncompatibility"
                    result["message"] = (
                        f"Operation '{operation}' requires a numeric column, but '{col}' "
                        f"is dtype '{df[col].dtype}' and cannot be coerced."
                    )
                    results.append(result)
                    continue

        # ── Required parameters check ─────────────────────────────────────────
        op_def = get_operation(operation)
        if op_def:
            for req_param in op_def.get("required_params", []):
                if req_param not in parameters or parameters[req_param] is None:
                    result["status"] = "error"
                    result["error_type"] = "MissingParameter"
                    result["message"] = (
                        f"Operation '{operation}' requires parameter '{req_param}' "
                        f"but it was not provided."
                    )
                    break

        results.append(result)

    return results


def plan_has_errors(validation_results: list) -> bool:
    """Return True if any validation result has status='error'."""
    return any(r["status"] == "error" for r in validation_results)


def get_validation_errors(validation_results: list) -> list:
    """Return only error-level validation results."""
    return [r for r in validation_results if r["status"] == "error"]


def get_validation_warnings(validation_results: list) -> list:
    """Return only warning-level validation results."""
    return [r for r in validation_results if r["status"] == "warning"]
