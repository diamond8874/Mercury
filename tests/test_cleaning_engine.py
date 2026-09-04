"""
tests/test_cleaning_engine.py — Comprehensive Test Suite for Cleaning Engine & Intent Layer
========================================================================================
Tests all required cleaning operations, intent parsing, validation, execution safety,
and realistic natural-language prompts.
"""

import pytest
import pandas as pd
import numpy as np

from services.cleaning.intent_parser import build_cleaning_plan
from services.cleaning.validator import validate_plan
from services.cleaning.executor import execute_plan
from services.data_service import apply_column_transformation


@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "Customer_ID": ["C101", "C102", "C103", "C104", "C105", "C105"],
        "Age": [25, 30, np.nan, 45, 50, 50],
        "Gender": ["M", "F", "Male", "Female", "M", "M"],
        "Salary": ["$50,000", "$60,000", "$70,000", np.nan, "$90,000", "$90,000"],
        "Churn": [0, 1, 0, 1, 0, 0],
        "Registration_Date": ["2023-01-15", "15/02/2023", "2023-03-20", "25-Aug-2023", "August 30, 2023", "August 30, 2023"],
        "Notes": ["<b>Hello</b>", "World!", "test@example.com", "call +1234567890", "   trim me   ", "   trim me   "],
        "Constant_Col": ["Same", "Same", "Same", "Same", "Same", "Same"],
        "Weight_kg": [70.0, 80.0, 65.0, 90.0, 75.0, 75.0]
    })


# ── 1. COLUMN OPERATIONS ──────────────────────────────────────────────────────

def test_drop_column(sample_df):
    df, msg = apply_column_transformation(sample_df.copy(), "Customer_ID", "drop column")
    assert "Customer_ID" not in df.columns


def test_keep_column(sample_df):
    # Keep action must NOT modify data or impute missing values
    df_copy = sample_df.copy()
    plan = build_cleaning_plan("Age", "keep Age unchanged", df_copy)
    res = execute_plan(plan, df_copy)
    # Age has np.nan at index 2; keep must preserve NaN and NOT impute it with median
    assert res["df"]["Age"].isnull().iloc[2]


def test_keep_only_columns(sample_df):
    df_copy = sample_df.copy()
    plan = build_cleaning_plan(None, "keep only Age, Gender and Salary", df_copy)
    res = execute_plan(plan, df_copy)
    cleaned = res["df"]
    assert list(cleaned.columns) == ["Age", "Gender", "Salary"]


def test_rename_column(sample_df):
    df, msg = apply_column_transformation(sample_df.copy(), "Customer_ID", "rename to User_ID")
    assert "User_ID" in df.columns
    assert "Customer_ID" not in df.columns


def test_move_column_front_end(sample_df):
    df1, msg1 = apply_column_transformation(sample_df.copy(), "Salary", "move to front")
    assert df1.columns[0] == "Salary"

    df2, msg2 = apply_column_transformation(sample_df.copy(), "Age", "move to end")
    assert df2.columns[-1] == "Age"


def test_drop_constant_column(sample_df):
    df, msg = apply_column_transformation(sample_df.copy(), "Constant_Col", "drop constant column")
    assert "Constant_Col" not in df.columns


# ── 2. MISSING VALUES ─────────────────────────────────────────────────────────

def test_impute_mean_median_mode_zero(sample_df):
    df1, _ = apply_column_transformation(sample_df.copy(), "Age", "fill missing with mean")
    assert not df1["Age"].isnull().any()

    df2, _ = apply_column_transformation(sample_df.copy(), "Age", "fill missing with median")
    assert not df2["Age"].isnull().any()

    df3, _ = apply_column_transformation(sample_df.copy(), "Gender", "fill missing with mode")
    assert not df3["Gender"].isnull().any()

    df4, _ = apply_column_transformation(sample_df.copy(), "Age", "fill missing with 0")
    assert (df4["Age"].fillna(0) == df4["Age"]).all()


def test_custom_fill(sample_df):
    df, _ = apply_column_transformation(sample_df.copy(), "Gender", "fill missing with Unknown")
    assert "Unknown" in df["Gender"].values or not df["Gender"].isnull().any()


def test_drop_null_rows(sample_df):
    df_copy = sample_df.copy()
    plan = build_cleaning_plan(None, "drop null rows", df_copy)
    res = execute_plan(plan, df_copy)
    assert not res["df"].isnull().any().any()


def test_column_specific_null_removal(sample_df):
    df_copy = sample_df.copy()
    plan = build_cleaning_plan("Age", "remove rows where Age is null", df_copy)
    res = execute_plan(plan, df_copy)
    assert not res["df"]["Age"].isnull().any()
    assert len(res["df"]) == len(sample_df) - 1


# ── 3. DUPLICATES ─────────────────────────────────────────────────────────────

def test_full_duplicate_removal(sample_df):
    df_copy = sample_df.copy()
    plan = build_cleaning_plan(None, "remove full duplicate rows", df_copy)
    res = execute_plan(plan, df_copy)
    assert len(res["df"]) == 5  # Row index 5 is an exact duplicate of index 4


def test_duplicate_by_column_keep_first_last(sample_df):
    df_copy = sample_df.copy()
    plan1 = build_cleaning_plan("Customer_ID", "remove duplicates based on Customer_ID and keep first record", df_copy)
    res1 = execute_plan(plan1, df_copy)
    assert res1["df"]["Customer_ID"].nunique() == len(res1["df"])

    plan2 = build_cleaning_plan("Customer_ID", "remove duplicates based on Customer_ID and keep last record", df_copy)
    res2 = execute_plan(plan2, df_copy)
    assert res2["df"]["Customer_ID"].nunique() == len(res2["df"])


# ── 4. TEXT CLEANING ──────────────────────────────────────────────────────────

def test_text_casing_and_trim(sample_df):
    df1, _ = apply_column_transformation(sample_df.copy(), "Notes", "uppercase")
    assert df1["Notes"].str.isupper().all() or df1["Notes"].iloc[0] == "<B>HELLO</B>"

    df2, _ = apply_column_transformation(sample_df.copy(), "Notes", "trim whitespace")
    assert df2["Notes"].iloc[4] == "trim me"


def test_strip_html_punctuation_stopwords(sample_df):
    df1, _ = apply_column_transformation(sample_df.copy(), "Notes", "strip html tags")
    assert "<b>" not in df1["Notes"].iloc[0]

    df2, _ = apply_column_transformation(sample_df.copy(), "Notes", "strip punctuation")
    assert "!" not in df2["Notes"].iloc[1]


def test_text_extractions(sample_df):
    df, _ = apply_column_transformation(sample_df.copy(), "Notes", "extract email")
    assert "Notes_email" in df.columns
    assert df["Notes_email"].iloc[2] == "test@example.com"


# ── 5. ENCODING ───────────────────────────────────────────────────────────────

def test_encodings(sample_df):
    df1, _ = apply_column_transformation(sample_df.copy(), "Gender", "one-hot encode")
    assert any(c.startswith("Gender_") for c in df1.columns)

    df2, _ = apply_column_transformation(sample_df.copy(), "Churn", "normalize bool")
    assert set(df2["Churn"].dropna().unique()).issubset({0, 1})


# ── 6. NUMERIC & DATATYPE CONVERSIONS ──────────────────────────────────────────

def test_currency_symbol_removal(sample_df):
    df, _ = apply_column_transformation(sample_df.copy(), "Salary", "remove currency symbol")
    assert pd.api.types.is_numeric_dtype(df["Salary"])


def test_explicit_datatype_conversion(sample_df):
    # "Convert Age to integer" must change dtype to integer, NOT round values
    df_copy = sample_df.copy()
    plan = build_cleaning_plan("Age", "Convert Age to integer", df_copy)
    res = execute_plan(plan, df_copy)
    assert pd.api.types.is_integer_dtype(res["df"]["Age"]) or str(res["df"]["Age"].dtype).startswith("Int")


def test_unit_conversions(sample_df):
    df, _ = apply_column_transformation(sample_df.copy(), "Weight_kg", "kg to lb")
    assert round(df["Weight_kg"].iloc[0], 1) == 154.3


# ── 7. DATETIME ───────────────────────────────────────────────────────────────

def test_date_extractions_and_parsing(sample_df):
    df1, _ = apply_column_transformation(sample_df.copy(), "Registration_Date", "extract year")
    assert "Registration_Date_year" in df1.columns

    df2, _ = apply_column_transformation(sample_df.copy(), "Registration_Date", "standardize date format")
    assert "Registration_Date" in df2.columns


# ── 8. OUTLIERS & ROW FILTERING ───────────────────────────────────────────────

def test_outliers_iqr(sample_df):
    df, _ = apply_column_transformation(sample_df.copy(), "Weight_kg", "clip iqr outliers")
    assert "Weight_kg" in df.columns


def test_row_filtering(sample_df):
    df_copy = sample_df.copy()
    plan = build_cleaning_plan(None, "remove rows where Age is below 30", df_copy)
    res = execute_plan(plan, df_copy)
    # Age values were 25, 30, NaN, 45, 50, 50. Row with 25 is removed.
    assert not (res["df"]["Age"] < 30).any()


# ── 9. REALISTIC NL PROMPT SAFETY TESTS ──────────────────────────────────────

def test_prompt_safety_remove_customer_id(sample_df):
    plan = build_cleaning_plan("Customer_ID", "Remove the Customer_ID column", sample_df)
    res = execute_plan(plan, sample_df.copy())
    assert "Customer_ID" not in res["df"].columns
    assert "Age" in res["df"].columns


def test_prompt_safety_keep_age_unchanged(sample_df):
    plan = build_cleaning_plan("Age", "Keep Age unchanged", sample_df)
    res = execute_plan(plan, sample_df.copy())
    # Ensure no imputation occurred
    assert res["df"]["Age"].isnull().iloc[2]


def test_prompt_safety_unsupported_instruction(sample_df):
    plan = build_cleaning_plan("Age", "Fix Age", sample_df)
    res = execute_plan(plan, sample_df.copy())
    # Unsupported / ambiguous instruction must NOT modify data
    assert res["df"]["Age"].isnull().iloc[2]
    assert len(res["warnings"]) > 0 or res["audit_log"][0]["status"] == "skipped"


def test_prompt_safety_broad_clean_dataset(sample_df):
    plan = build_cleaning_plan(None, "clean dataset", sample_df)
    res = execute_plan(plan, sample_df.copy())
    # Broad instruction must produce an ambiguous warning and NOT silently drop rows or cols
    assert len(res["df"]) == len(sample_df)
    assert list(res["df"].columns) == list(sample_df.columns)
