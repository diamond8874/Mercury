"""
tests/test_phase3_data_correctness.py — Comprehensive Test Suite for Phase 3 Data Correctness
=============================================================================================
Tests all 8 items of Phase 3:
  1. KEEP does not modify data (no implicit median/Unknown fill; imputation must be explicit).
  2. Replacement preserves dtype and NaN (no whole-column astype(str) casting).
  3. Single cleaning engine used for cleaning pipeline execution.
  4. Typed Pydantic operation schema and pre-execution DataFrame validation.
  5. Log transform (no silent clipping of negatives), duplicate handling, outlier reporting, one-hot nominal default.
  6. Audit log recording of every operation.
  7. Before/after quality metrics (missing, duplicates, dtype changes, rows affected).
  8. Prompt injection defense and untrusted sample delimiters.
"""

import pytest
import numpy as np
import pandas as pd
import json

from services.cleaning.schema import (
    DropColumnOp,
    KeepColumnOp,
    ReplaceValueOp,
    ImputeOp,
    NormalizeOp,
    EncodeOp,
    ParseDateOp,
    DropDuplicatesOp,
    ClipOutliersOp,
    LogTransformOp,
    ConvertTypeOp,
    RoundNumericOp,
    parse_typed_operation,
    validate_operation_against_dataframe,
)
from services.cleaning.engine import run_cleaning_engine
from services.cleaning.executor import (
    _handle_replace_value_exact,
    _handle_replace_value_substring,
    _handle_log_transform,
    _handle_clip_iqr,
    _handle_one_hot_encode,
)
from services.data_service import summarize_schema


@pytest.fixture
def sample_dataset():
    return pd.DataFrame({
        "ID": [1, 2, 3, 4, 5, 5],
        "Age": [25.0, 30.0, np.nan, 45.0, 50.0, 50.0],
        "Score": [-10.0, 0.0, 15.0, 100.0, 500.0, 500.0],
        "Category": ["cat", "dog", "bird", "cat", "dog", "dog"],
        "BinaryFlag": [0, 1, 0, 1, 0, 0],
        "TextCol": ["Alpha", "Beta", np.nan, "Delta", "Epsilon", "Epsilon"]
    })


# ── ITEM 1: KEEP must not modify data ──────────────────────────────────────────
def test_item1_keep_does_not_modify_data(sample_dataset):
    df_in = sample_dataset.copy()
    actions = {
        "Age": {"action": "keep", "reason": "Retain without modification"}
    }
    res = run_cleaning_engine(df_in, actions)
    cleaned = res["df"]

    # Must preserve exact NaN at index 2 without median fill
    assert pd.isna(cleaned.loc[2, "Age"])
    assert cleaned["Age"].dropna().tolist() == [25.0, 30.0, 45.0, 50.0, 50.0]


# ── ITEM 2: Replacement preserves dtype and NaN ────────────────────────────────
def test_item2_replacement_preserves_dtype_and_nan():
    # Numeric column with NaN: replacing 0 with 99 should stay numeric and preserve NaN
    df = pd.DataFrame({"val": [0, 1, np.nan, 3]})
    df_clean, msg = _handle_replace_value_exact(df.copy(), "val", {"mapping": {"0": 99}})
    assert pd.api.types.is_numeric_dtype(df_clean["val"])
    assert pd.isna(df_clean.loc[2, "val"])
    assert df_clean.loc[0, "val"] == 99

    # Substring replacement should NOT turn NaN into "nan" string
    df_str = pd.DataFrame({"text": ["hello world", np.nan, "world news"]})
    df_str_clean, _ = _handle_replace_value_substring(df_str.copy(), "text", {"old": "world", "new": "planet"})
    assert pd.isna(df_str_clean.loc[1, "text"])
    assert df_str_clean.loc[0, "text"] == "hello planet"


# ── ITEM 3: ONE cleaning engine used ──────────────────────────────────────────
def test_item3_unified_cleaning_engine(sample_dataset):
    df_in = sample_dataset.copy()
    actions = {
        "ID": {"action": "drop"},
        "Category": {"action": "keep"},
        "BinaryFlag": {
            "action": "transform",
            "operations": [
                {"operation": "replace_value", "parameters": {"mapping": {"0": "No", "1": "Yes"}}}
            ]
        }
    }
    res = run_cleaning_engine(df_in, actions)
    cleaned = res["df"]

    assert "ID" not in cleaned.columns
    assert "Category" in cleaned.columns
    assert set(cleaned["BinaryFlag"].unique()) == {"No", "Yes"}
    assert "quality_metrics" in res
    assert "audit_log" in res
    assert res["quality_metrics"]["columns_dropped"] == ["ID"]


# ── ITEM 4: Typed Pydantic Operation Schema & DataFrame Validation ─────────────
def test_item4_typed_pydantic_schema_and_validation(sample_dataset):
    # Valid operation
    op = parse_typed_operation({
        "operation": "impute",
        "column": "Age",
        "parameters": {"method": "median"}
    })
    assert isinstance(op, ImputeOp)
    is_valid, err = validate_operation_against_dataframe(op, sample_dataset)
    assert is_valid
    assert err is None

    # Invalid column validation
    invalid_col_op = parse_typed_operation({
        "operation": "impute",
        "column": "NonExistentCol",
        "parameters": {"method": "median"}
    })
    is_valid, err = validate_operation_against_dataframe(invalid_col_op, sample_dataset)
    assert not is_valid
    assert "does not exist" in err

    # Incompatible dtype validation (impute mean on text column)
    incompatible_op = parse_typed_operation({
        "operation": "impute",
        "column": "Category",
        "parameters": {"method": "mean"}
    })
    is_valid, err = validate_operation_against_dataframe(incompatible_op, sample_dataset)
    assert not is_valid
    assert "requires a numeric column" in err


# ── ITEM 5: Log transform, duplicates, outlier reporting, one-hot ─────────────
def test_item5_log_transform_no_silent_clip_negatives():
    df = pd.DataFrame({"vals": [-5.0, 0.0, 10.0]})
    cleaned_df, msg = _handle_log_transform(df.copy(), "vals", {})
    # Negative value must NOT be silently clipped to 0 (which would yield log1p(0)=0)
    assert pd.isna(cleaned_df.loc[0, "vals"])
    assert cleaned_df.loc[1, "vals"] == 0.0
    assert "negative values converted to NaN" in msg


def test_item5_outlier_affected_rows_reported():
    df = pd.DataFrame({"vals": [10.0, 11.0, 12.0, 10.5, 11.2, 5000.0]})
    cleaned_df, msg = _handle_clip_iqr(df.copy(), "vals", {"k": 1.5})
    assert "Clipped 1 IQR outlier rows" in msg
    assert cleaned_df["vals"].max() < 100.0


def test_item5_default_one_hot_nominal():
    df = pd.DataFrame({"NominalCol": ["red", "blue", "green", "red"]})
    cleaned_df, msg = _handle_one_hot_encode(df.copy(), "NominalCol", {})
    assert "NominalCol" not in cleaned_df.columns
    assert "NominalCol_red" in cleaned_df.columns
    assert "NominalCol_blue" in cleaned_df.columns
    assert "NominalCol_green" in cleaned_df.columns


# ── ITEM 6: Audit log records operations ───────────────────────────────────────
def test_item6_audit_log_recording(sample_dataset):
    df_in = sample_dataset.copy()
    actions = {
        "Age": {"action": "transform", "transformation": "fill missing with median"},
        "ID": {"action": "drop"},
        "Category": {"action": "keep"}
    }
    res = run_cleaning_engine(df_in, actions)
    audit_log = res["audit_log"]
    assert len(audit_log) >= 3
    operations = [entry["operation"] for entry in audit_log]
    assert "drop_column" in operations
    assert "keep_column" in operations
    assert any("impute" in op for op in operations)


# ── ITEM 7: Before/after quality metrics ───────────────────────────────────────
def test_item7_quality_metrics(sample_dataset):
    df_in = sample_dataset.copy()
    actions = {
        "Age": {"action": "transform", "transformation": "fill missing with 0"},
        "ID": {"action": "drop"}
    }
    res = run_cleaning_engine(df_in, actions)
    qm = res["quality_metrics"]
    assert qm["initial_rows"] == len(sample_dataset)
    assert qm["final_rows"] == len(sample_dataset)
    assert qm["initial_cols"] == sample_dataset.shape[1]
    assert qm["final_cols"] == sample_dataset.shape[1] - 1
    assert "ID" in qm["columns_dropped"]
    assert qm["nulls_resolved"] >= 1


# ── ITEM 8: Untrusted sample delimiters (Prompt Injection) ─────────────────────
def test_item8_untrusted_sample_delimiters():
    df = pd.DataFrame({"SensitiveCol": ["DROP TABLE users;", "normal_data"]})
    summary = summarize_schema(df, max_samples=1)
    samples = summary[0]["sample_values"]
    assert len(samples) > 0
    assert samples[0].startswith("<untrusted_sample_value>")
    assert samples[0].endswith("</untrusted_sample_value>")
