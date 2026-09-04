"""
executor.py — Safe Execution Engine for Structured Cleaning Plans
=================================================================
Takes a validated cleaning plan and executes operations in order.

Key guarantees:
  - No eval() or exec()
  - One handler per operation; failures are isolated
  - Returns full audit trail
  - Does NOT silently fall back to imputation for unrecognized ops
  - "keep_column" is a true no-op
  - "unsupported" / "ambiguous_instruction" are always no-ops
"""

import re
import logging
import datetime
import pandas as pd
import numpy as np

from services.cleaning.audit import make_operation_log, OperationTimer
from services.cleaning.operation_registry import UNIT_CONVERSIONS, DTYPE_CONVERSION_TARGETS


# ── No-op operations (execute nothing, generate informational log) ────────────
_NOOP_OPERATIONS = {"keep_column", "unsupported", "ambiguous_instruction", "ambiguous_column"}

# Common fake-null placeholder patterns
_FAKE_NULL_PATTERN = re.compile(
    r'^\s*(?:n/?a|none|null|undefined|empty|nan|-|\?)\s*$',
    re.IGNORECASE
)

# Stopword set for stopword removal
_STOPWORDS = {
    'a', 'an', 'the', 'and', 'or', 'in', 'on', 'at', 'to', 'for',
    'with', 'by', 'of', 'is', 'it', 'this', 'that', 'from', 'as',
    'are', 'was', 'be', 'but', 'not', 'so', 'if', 'do', 'did', 'has', 'have',
}

# Boolean normalization map
_BOOL_MAP = {
    'yes': 1, 'y': 1, 'true': 1, 't': 1, '1': 1, '1.0': 1,
    'no': 0, 'n': 0, 'false': 0, 'f': 0, '0': 0, '0.0': 0,
}

# Supported datetime parse formats (ordered most-specific first)
_DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%b-%Y",          # 25-Aug-2025
    "%d %B %Y",          # 25 August 2025
    "%B %d, %Y",         # August 25, 2025
    "%b %d, %Y",         # Aug 25, 2025
    "%m/%d/%Y",
    "%m-%d-%Y",
]


def _parse_date_str(v_str: str) -> str:
    """Try multiple formats to parse a date string; return ISO or original."""
    v_str = v_str.strip()
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.datetime.strptime(v_str, fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            pass
    return v_str


def _safe_col_stats(df: pd.DataFrame, col: str) -> tuple:
    """Return (row_count, null_count) for a column, safely."""
    if col not in df.columns:
        return (len(df), 0)
    return (len(df), int(df[col].isnull().sum()))


# ── Individual operation handlers ─────────────────────────────────────────────

def _handle_drop_column(df: pd.DataFrame, col: str, params: dict) -> tuple:
    if col in df.columns:
        df = df.drop(columns=[col])
        return df, f"Dropped column '{col}'."
    return df, f"Column '{col}' not found (already dropped or invalid)."


def _handle_rename_column(df: pd.DataFrame, col: str, params: dict) -> tuple:
    new_name = params.get("new_name", "")
    if not new_name:
        return df, f"No new name specified for rename of '{col}'."
    df = df.rename(columns={col: new_name})
    return df, f"Renamed '{col}' → '{new_name}'."


def _handle_move_front(df: pd.DataFrame, col: str, params: dict) -> tuple:
    cols = [col] + [c for c in df.columns if c != col]
    df = df[cols]
    return df, f"Moved '{col}' to front."


def _handle_move_end(df: pd.DataFrame, col: str, params: dict) -> tuple:
    cols = [c for c in df.columns if c != col] + [col]
    df = df[cols]
    return df, f"Moved '{col}' to end."


def _handle_drop_constant(df: pd.DataFrame, col: str, params: dict) -> tuple:
    if df[col].nunique(dropna=True) <= 1:
        df = df.drop(columns=[col])
        return df, f"Dropped constant column '{col}'."
    return df, f"Column '{col}' is not constant (skipped)."


def _handle_keep_only_columns(df: pd.DataFrame, col: str, params: dict) -> tuple:
    keep_cols = params.get("columns", [])
    valid_keep = [c for c in keep_cols if c in df.columns]
    invalid = [c for c in keep_cols if c not in df.columns]
    df = df[valid_keep]
    msg = f"Kept only columns: {valid_keep}."
    if invalid:
        msg += f" (Not found and ignored: {invalid})"
    return df, msg


def _handle_normalize_missing(df: pd.DataFrame, col: str, params: dict) -> tuple:
    before_nulls = int(df[col].isnull().sum())
    df[col] = df[col].astype(str).apply(
        lambda v: np.nan if _FAKE_NULL_PATTERN.match(v) else v
    )
    df[col] = df[col].replace([np.inf, -np.inf], np.nan)
    after_nulls = int(df[col].isnull().sum())
    return df, f"Normalized fake nulls in '{col}': {after_nulls - before_nulls} new NaNs."


def _handle_handle_infinity(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df[col] = pd.to_numeric(df[col], errors='coerce').replace([np.inf, -np.inf], np.nan)
    return df, f"Replaced inf/-inf with NaN in '{col}'."


def _handle_normalize_blank(df: pd.DataFrame, col: str, params: dict) -> tuple:
    before = int(df[col].isnull().sum())
    df[col] = df[col].apply(
        lambda v: np.nan if isinstance(v, str) and v.strip() == '' else v
    )
    after = int(df[col].isnull().sum())
    return df, f"Converted {after - before} blank strings to NaN in '{col}'."


def _handle_impute_mean(df: pd.DataFrame, col: str, params: dict) -> tuple:
    num_ser = pd.to_numeric(df[col], errors='coerce')
    filled = int(num_ser.isnull().sum())
    df.loc[:, col] = num_ser.fillna(num_ser.mean())
    return df, f"Filled {filled} missing values in '{col}' with mean."


def _handle_impute_median(df: pd.DataFrame, col: str, params: dict) -> tuple:
    num_ser = pd.to_numeric(df[col], errors='coerce')
    filled = int(num_ser.isnull().sum())
    df.loc[:, col] = num_ser.fillna(num_ser.median())
    return df, f"Filled {filled} missing values in '{col}' with median."


def _handle_impute_mode(df: pd.DataFrame, col: str, params: dict) -> tuple:
    mode_val = df[col].mode()
    if mode_val.empty:
        return df, f"No mode found for '{col}' (column may be all-null)."
    filled = int(df[col].isnull().sum())
    df.loc[:, col] = df[col].fillna(mode_val[0])
    return df, f"Filled {filled} missing values in '{col}' with mode ({mode_val[0]})."


def _handle_impute_zero(df: pd.DataFrame, col: str, params: dict) -> tuple:
    filled = int(df[col].isnull().sum())
    df.loc[:, col] = df[col].fillna(0)
    return df, f"Filled {filled} missing values in '{col}' with 0."


def _handle_impute_custom(df: pd.DataFrame, col: str, params: dict) -> tuple:
    fill_value = params.get("fill_value")
    if fill_value is None:
        return df, f"No fill value specified for custom imputation of '{col}'."
    filled = int(df[col].isnull().sum())
    df.loc[:, col] = df[col].fillna(fill_value)
    return df, f"Filled {filled} missing values in '{col}' with '{fill_value}'."


def _handle_drop_null_rows(df: pd.DataFrame, col: str, params: dict) -> tuple:
    before = len(df)
    df = df.dropna().reset_index(drop=True)
    removed = before - len(df)
    return df, f"Removed {removed} rows with any null value."


def _handle_drop_null_rows_column(df: pd.DataFrame, col: str, params: dict) -> tuple:
    target = params.get("column", col)
    if target not in df.columns:
        return df, f"Column '{target}' not found for null-row removal."
    before = len(df)
    df = df[df[target].notna()].reset_index(drop=True)
    removed = before - len(df)
    return df, f"Removed {removed} rows where '{target}' was null."


def _handle_drop_duplicates_full(df: pd.DataFrame, col: str, params: dict) -> tuple:
    before = len(df)
    df = df.drop_duplicates().reset_index(drop=True)
    removed = before - len(df)
    return df, f"Removed {removed} fully-duplicate rows."


def _handle_drop_duplicates_by_columns(df: pd.DataFrame, col: str, params: dict) -> tuple:
    subset = params.get("subset", [col])
    keep = params.get("keep", "first")
    if not subset:
        subset = [col]
    valid_subset = [c for c in subset if c in df.columns]
    if not valid_subset:
        return df, f"No valid columns in subset {subset} for deduplication."
    before = len(df)
    df = df.drop_duplicates(subset=valid_subset, keep=keep).reset_index(drop=True)
    removed = before - len(df)
    return df, (f"Removed {removed} duplicate rows based on {valid_subset}, "
                f"keep='{keep}'.")


def _handle_uppercase(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = df[col].astype(str).str.upper()
    return df, f"Converted '{col}' to uppercase."


def _handle_lowercase(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = df[col].astype(str).str.lower()
    return df, f"Converted '{col}' to lowercase."


def _handle_titlecase(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = df[col].astype(str).str.title()
    return df, f"Converted '{col}' to title case."


def _handle_strip_whitespace(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = df[col].astype(str).str.strip()
    return df, f"Stripped whitespace from '{col}'."


def _handle_remove_punctuation(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = df[col].astype(str).str.replace(r'[^\w\s]', '', regex=True)
    return df, f"Removed punctuation from '{col}'."


def _handle_remove_html(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = df[col].astype(str).str.replace(r'<[^>]+>', '', regex=True)
    return df, f"Stripped HTML tags from '{col}'."


def _handle_remove_stopwords(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df[col] = df[col].astype(str).apply(
        lambda text: " ".join(w for w in text.split() if w.lower() not in _STOPWORDS)
    )
    return df, f"Removed stopwords from '{col}'."


def _handle_string_length(df: pd.DataFrame, col: str, params: dict) -> tuple:
    new_col = f"{col}_len"
    df[new_col] = df[col].astype(str).str.len()
    return df, f"Created string-length column '{new_col}'."


def _handle_extract_digits(df: pd.DataFrame, col: str, params: dict) -> tuple:
    new_col = f"{col}_digits"
    df[new_col] = df[col].astype(str).str.extract(r'(\d+)', expand=False)
    return df, f"Extracted digits from '{col}' into '{new_col}'."


def _handle_extract_email(df: pd.DataFrame, col: str, params: dict) -> tuple:
    new_col = f"{col}_email"
    df[new_col] = df[col].astype(str).str.extract(
        r'([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', expand=False
    )
    return df, f"Extracted emails from '{col}' into '{new_col}'."


def _handle_extract_phone(df: pd.DataFrame, col: str, params: dict) -> tuple:
    new_col = f"{col}_phone"
    df[new_col] = df[col].astype(str).str.extract(r'(\+?\d[\d\s\-\(\)]{7,}\d)', expand=False)
    return df, f"Extracted phone numbers from '{col}' into '{new_col}'."


def _handle_split_column(df: pd.DataFrame, col: str, params: dict) -> tuple:
    sep = params.get("separator", " ")
    splits = df[col].astype(str).str.split(sep, expand=True)
    n_splits = min(splits.shape[1], 4)
    for i in range(n_splits):
        df[f"{col}_{i+1}"] = splits[i]
    return df, f"Split '{col}' by '{sep}' into {n_splits} columns."


def _handle_concat_column(df: pd.DataFrame, col: str, params: dict) -> tuple:
    other = params.get("other_col")
    if not other or other not in df.columns:
        return df, f"Cannot concatenate: column '{other}' not found."
    df[col] = df[col].astype(str) + " " + df[other].astype(str)
    return df, f"Concatenated '{col}' with '{other}'."


def _handle_replace_value_exact(df: pd.DataFrame, col: str, params: dict) -> tuple:
    mapping = params.get("mapping", {})
    if not mapping:
        return df, f"No replacement mapping provided for '{col}'."

    replacement_dict = {}
    for old_v, new_v in mapping.items():
        replacement_dict[old_v] = new_v
        replacement_dict[str(old_v).lower()] = new_v
        replacement_dict[str(old_v).upper()] = new_v
        try:
            num_val = float(old_v)
            if num_val.is_integer():
                int_val = int(num_val)
                replacement_dict[int_val] = new_v
                replacement_dict[float(int_val)] = new_v
                replacement_dict[str(int_val)] = new_v
                replacement_dict[f"{int_val}.0"] = new_v
            else:
                replacement_dict[num_val] = new_v
                replacement_dict[str(num_val)] = new_v
        except (ValueError, TypeError):
            pass

    df[col] = df[col].replace(replacement_dict)
    # Apply regex-based exact cell replacement for string columns
    for k, v in list(replacement_dict.items()):
        if isinstance(k, str):
            pattern = r'(?i)^' + re.escape(k) + r'$'
            try:
                df[col] = df[col].astype(str).replace(to_replace=pattern, value=v, regex=True)
            except Exception:
                pass

    desc = ", ".join([f"'{k}'→'{v}'" for k, v in mapping.items()])
    return df, f"Replaced values in '{col}': {desc}."


def _handle_replace_value_substring(df: pd.DataFrame, col: str, params: dict) -> tuple:
    old = params.get("old", "")
    new = params.get("new", "")
    if not old:
        return df, f"No substring specified for replacement in '{col}'."
    df[col] = df[col].astype(str).str.replace(old, new, regex=False)
    return df, f"Replaced substring '{old}' with '{new}' in '{col}'."


def _handle_replace_value_regex(df: pd.DataFrame, col: str, params: dict) -> tuple:
    pattern = params.get("pattern", "")
    replacement = params.get("replacement", "")
    if not pattern:
        return df, f"No regex pattern specified for '{col}'."
    df[col] = df[col].astype(str).str.replace(pattern, replacement, regex=True)
    return df, f"Applied regex replacement in '{col}': pattern='{pattern}'."


def _handle_one_hot_encode(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dummies = pd.get_dummies(df[col], prefix=col, drop_first=False)
    df = pd.concat([df.drop(columns=[col]), dummies], axis=1)
    return df, f"One-hot encoded '{col}' into {dummies.shape[1]} columns."


def _handle_ordinal_encode(df: pd.DataFrame, col: str, params: dict) -> tuple:
    order = params.get("order")
    if order:
        order_map = {val: idx for idx, val in enumerate(order)}
        df[col] = df[col].astype(str).map(order_map).fillna(-1).astype(int)
        return df, f"Ordinal encoded '{col}' with order: {order}."
    else:
        uniques = sorted(df[col].dropna().astype(str).unique())
        order_map = {val: idx for idx, val in enumerate(uniques)}
        df[col] = df[col].astype(str).map(order_map).fillna(-1).astype(int)
        return df, f"Ordinal encoded '{col}' (auto-sorted: {uniques[:5]}...)."


def _handle_frequency_encode(df: pd.DataFrame, col: str, params: dict) -> tuple:
    freqs = df[col].value_counts(normalize=True, dropna=False)
    df[col] = df[col].map(freqs)
    return df, f"Frequency encoded '{col}' by proportion."


def _handle_label_encode(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df[col] = df[col].astype('category').cat.codes
    return df, f"Label encoded '{col}'."


def _handle_normalize_boolean(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = df[col].astype(str).str.lower().str.strip().map(_BOOL_MAP)
    return df, f"Normalized boolean values in '{col}' to 1/0."


def _handle_convert_percentage(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = pd.to_numeric(df[col].astype(str).str.replace('%', '', regex=False), errors='coerce') / 100.0
    return df, f"Parsed percentage values in '{col}' to decimals."


def _handle_parse_accounting_currency(df: pd.DataFrame, col: str, params: dict) -> tuple:
    def _parse(val):
        if pd.isna(val): return np.nan
        s = str(val).strip()
        if s.startswith('(') and s.endswith(')'):
            s = '-' + s[1:-1]
        s = re.sub(r'[\$,€£\s]', '', s)
        try: return float(s)
        except: return np.nan
    df.loc[:, col] = df[col].apply(_parse)
    return df, f"Parsed accounting currency in '{col}'."


def _handle_remove_currency_symbol(df: pd.DataFrame, col: str, params: dict) -> tuple:
    cleaned = df[col].astype(str).str.replace(r'[\$,€£\s]', '', regex=True)
    df[col] = pd.to_numeric(cleaned, errors='coerce')
    return df, f"Removed currency symbols from '{col}' and converted to numeric."


def _handle_normalize_minmax(df: pd.DataFrame, col: str, params: dict) -> tuple:
    num = pd.to_numeric(df[col], errors='coerce')
    min_v, max_v = num.min(), num.max()
    if max_v != min_v:
        df.loc[:, col] = (num - min_v) / (max_v - min_v)
    else:
        df.loc[:, col] = 0.0
    return df, f"Applied Min-Max normalization to '{col}'."


def _handle_standardize_zscore(df: pd.DataFrame, col: str, params: dict) -> tuple:
    num = pd.to_numeric(df[col], errors='coerce')
    std_v = num.std()
    if std_v and std_v != 0:
        df.loc[:, col] = (num - num.mean()) / std_v
    return df, f"Applied Z-score standardization to '{col}'."


def _handle_log_transform(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df.loc[:, col] = np.log1p(pd.to_numeric(df[col], errors='coerce').clip(lower=0))
    return df, f"Applied log(1+x) transformation to '{col}'."


def _handle_round_values(df: pd.DataFrame, col: str, params: dict) -> tuple:
    decimals = params.get("decimals", 0)
    df[col] = pd.to_numeric(df[col], errors='coerce').round(decimals)
    return df, f"Rounded '{col}' to {decimals} decimal places."


def _handle_convert_datatype(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dtype = params.get("dtype", "")
    if not dtype:
        return df, f"No target dtype specified for conversion of '{col}'."
    try:
        if dtype == "int":
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
        elif dtype == "float":
            df[col] = pd.to_numeric(df[col], errors='coerce').astype(float)
        elif dtype == "str":
            df[col] = df[col].astype(str)
        elif dtype == "bool":
            df[col] = df[col].astype(bool)
        elif dtype == "category":
            df[col] = df[col].astype('category')
        elif dtype == "datetime":
            df[col] = pd.to_datetime(df[col], errors='coerce', infer_datetime_format=True)
        else:
            df[col] = df[col].astype(dtype)
        return df, f"Converted '{col}' to dtype '{dtype}'."
    except Exception as e:
        return df, f"Failed to convert '{col}' to '{dtype}': {e}."


def _handle_convert_unit(df: pd.DataFrame, col: str, params: dict) -> tuple:
    from_u = (params.get("from_unit") or "").lower().strip()
    to_u = (params.get("to_unit") or "").lower().strip()
    converter = UNIT_CONVERSIONS.get((from_u, to_u))
    if not converter:
        return df, f"No unit converter found for '{from_u}' → '{to_u}'."
    num = pd.to_numeric(df[col], errors='coerce')
    df[col] = num.apply(lambda v: converter(v) if pd.notna(v) else np.nan)
    return df, f"Converted '{col}' from {from_u} to {to_u}."


def _handle_derived_math(df: pd.DataFrame, col: str, params: dict) -> tuple:
    operation = params.get("operation", "")
    target = params.get("target", "")
    if not target or target not in df.columns:
        return df, f"Derived math: column '{target}' not found."
    num1 = pd.to_numeric(df[col], errors='coerce')
    num2 = pd.to_numeric(df[target], errors='coerce')
    new_col = f"{col}_{operation[:3]}_{target}"
    if operation == "multiply":
        df[new_col] = num1 * num2
    elif operation == "add":
        df[new_col] = num1 + num2
    elif operation == "subtract":
        df[new_col] = num1 - num2
    elif operation == "divide":
        df[new_col] = num1 / num2
    else:
        return df, f"Unknown math operation '{operation}'."
    return df, f"Created derived column '{new_col}' ({col} {operation} {target})."


def _safe_to_datetime(series: pd.Series) -> pd.Series:
    """Safely convert a pandas Series to datetime without triggering C-extension crashes on mixed format strings."""
    def parse_dt(v):
        if pd.isna(v) or v is None:
            return pd.NaT
        if isinstance(v, (pd.Timestamp, datetime.datetime)):
            return pd.Timestamp(v)
        v_str = str(v).strip()
        if not v_str:
            return pd.NaT
        for fmt in _DATE_FORMATS:
            try:
                dt = datetime.datetime.strptime(v_str, fmt)
                return pd.Timestamp(dt)
            except (ValueError, TypeError):
                pass
        return pd.NaT

    return pd.Series([parse_dt(v) for v in series], index=series.index, dtype="object")





def _handle_extract_year(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    df[f"{col}_year"] = dt.apply(lambda x: x.year if pd.notna(x) else np.nan)
    return df, f"Extracted year from '{col}'."


def _handle_extract_month(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    df[f"{col}_month"] = dt.apply(lambda x: x.month if pd.notna(x) else np.nan)
    return df, f"Extracted month from '{col}'."


def _handle_extract_day(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    df[f"{col}_day"] = dt.apply(lambda x: x.day if pd.notna(x) else np.nan)
    return df, f"Extracted day from '{col}'."


def _handle_extract_weekday(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    df[f"{col}_weekday"] = dt.apply(lambda x: x.day_name() if pd.notna(x) else np.nan)
    return df, f"Extracted weekday from '{col}'."


def _handle_extract_quarter(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    df[f"{col}_quarter"] = dt.apply(lambda x: x.quarter if pd.notna(x) else np.nan)
    return df, f"Extracted quarter from '{col}'."


def _handle_extract_hour(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    df[f"{col}_hour"] = dt.apply(lambda x: x.hour if pd.notna(x) else np.nan)
    return df, f"Extracted hour from '{col}'."


def _handle_extract_minute(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    df[f"{col}_minute"] = dt.apply(lambda x: x.minute if pd.notna(x) else np.nan)
    return df, f"Extracted minute from '{col}'."


def _handle_extract_weekend(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    df[f"{col}_is_weekend"] = dt.apply(lambda x: 1 if pd.notna(x) and x.weekday() in (5, 6) else 0)
    return df, f"Created is_weekend feature from '{col}'."


def _handle_days_since(df: pd.DataFrame, col: str, params: dict) -> tuple:
    dt = _safe_to_datetime(df[col])
    now = pd.Timestamp.now()
    df[f"{col}_days_since"] = dt.apply(lambda x: (now - x).days if pd.notna(x) else np.nan)
    return df, f"Calculated days since today for '{col}'."


def _handle_date_difference(df: pd.DataFrame, col: str, params: dict) -> tuple:
    ref_col = params.get("ref_col")
    use_today = params.get("use_today", False)
    dt = _safe_to_datetime(df[col])
    now = pd.Timestamp.now()
    if use_today or not ref_col:
        df[f"{col}_days_since"] = dt.apply(lambda x: (now - x).days if pd.notna(x) else np.nan)
        return df, f"Calculated days since today for '{col}'."
    if ref_col not in df.columns:
        return df, f"Reference column '{ref_col}' not found."
    ref_dt = _safe_to_datetime(df[ref_col])
    df[f"{col}_diff_{ref_col}"] = [
        (d1 - d2).days if (pd.notna(d1) and pd.notna(d2)) else np.nan
        for d1, d2 in zip(dt, ref_dt)
    ]
    return df, f"Calculated date difference between '{col}' and '{ref_col}'."




def _handle_standardize_datetime(df: pd.DataFrame, col: str, params: dict) -> tuple:
    df[col] = df[col].apply(
        lambda v: _parse_date_str(str(v)) if pd.notna(v) else v
    )
    return df, f"Standardized datetime format in '{col}'."


def _handle_clip_iqr(df: pd.DataFrame, col: str, params: dict) -> tuple:
    num = pd.to_numeric(df[col], errors='coerce')
    q1, q3 = num.quantile(0.25), num.quantile(0.75)
    iqr = q3 - q1
    lower_b, upper_b = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    df.loc[:, col] = num.clip(lower=lower_b, upper=upper_b)
    return df, f"Clipped IQR outliers in '{col}' (fence: [{lower_b:.2f}, {upper_b:.2f}])."


def _handle_drop_iqr_rows(df: pd.DataFrame, col: str, params: dict) -> tuple:
    num = pd.to_numeric(df[col], errors='coerce')
    q1, q3 = num.quantile(0.25), num.quantile(0.75)
    iqr = q3 - q1
    lower_b, upper_b = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    before = len(df)
    df = df[(num >= lower_b) & (num <= upper_b)].reset_index(drop=True)
    removed = before - len(df)
    return df, f"Removed {removed} IQR outlier rows based on '{col}'."


def _handle_clip_percentile(df: pd.DataFrame, col: str, params: dict) -> tuple:
    num = pd.to_numeric(df[col], errors='coerce')
    low, high = num.quantile(0.01), num.quantile(0.99)
    df[col] = num.clip(lower=low, upper=high)
    return df, f"Clipped 1st–99th percentile outliers in '{col}'."


def _handle_filter_rows(df: pd.DataFrame, col: str, params: dict) -> tuple:
    f_col = params.get("col", "")
    f_op = params.get("op", "")
    f_val = params.get("val", "")
    if not f_col or f_col not in df.columns:
        return df, f"Filter column '{f_col}' not found."
    before = len(df)
    try:
        f_val_num = float(f_val)
        num_ser = pd.to_numeric(df[f_col], errors='coerce')
        if f_op == '>': mask = num_ser > f_val_num
        elif f_op == '<': mask = num_ser < f_val_num
        elif f_op == '>=': mask = num_ser >= f_val_num
        elif f_op == '<=': mask = num_ser <= f_val_num
        elif f_op in ('==', '='): mask = num_ser == f_val_num
        elif f_op == '!=': mask = num_ser != f_val_num
        else: mask = pd.Series([True] * len(df))
    except (ValueError, TypeError):
        str_ser = df[f_col].astype(str)
        if f_op in ('==', '='): mask = str_ser == f_val
        elif f_op == '!=': mask = str_ser != f_val
        else: mask = pd.Series([True] * len(df))
    df = df[mask].reset_index(drop=True)
    return df, f"Kept {len(df)}/{before} rows where {f_col} {f_op} {f_val}."


def _handle_remove_rows(df: pd.DataFrame, col: str, params: dict) -> tuple:
    f_col = params.get("col", "")
    f_op = params.get("op", "")
    f_val = params.get("val", "")
    if not f_col or f_col not in df.columns:
        return df, f"Filter column '{f_col}' not found."
    before = len(df)
    try:
        f_val_num = float(f_val)
        num_ser = pd.to_numeric(df[f_col], errors='coerce')
        if f_op == '>': mask = num_ser > f_val_num
        elif f_op == '<': mask = num_ser < f_val_num
        elif f_op == '>=': mask = num_ser >= f_val_num
        elif f_op == '<=': mask = num_ser <= f_val_num
        elif f_op in ('==', '='): mask = num_ser == f_val_num
        elif f_op == '!=': mask = num_ser != f_val_num
        else: mask = pd.Series([True] * len(df))
    except (ValueError, TypeError):
        str_ser = df[f_col].astype(str)
        if f_op in ('==', '='): mask = str_ser == f_val
        elif f_op == '!=': mask = str_ser != f_val
        else: mask = pd.Series([True] * len(df))
    df = df[~mask].reset_index(drop=True)
    removed = before - len(df)
    return df, f"Removed {removed} rows where {f_col} {f_op} {f_val}."


def _handle_explode_column(df: pd.DataFrame, col: str, params: dict) -> tuple:
    sep = params.get("separator", ";")
    df[col] = df[col].astype(str).str.split(sep)
    df = df.explode(col, ignore_index=True)
    return df, f"Exploded '{col}' by '{sep}'."


def _handle_bin_column(df: pd.DataFrame, col: str, params: dict) -> tuple:
    num_bins = params.get("num_bins", 4)
    num = pd.to_numeric(df[col], errors='coerce')
    new_col = f"{col}_binned"
    try:
        df[new_col] = pd.qcut(num, q=num_bins, duplicates='drop').astype(str)
        return df, f"Binned '{col}' into {num_bins} quantile buckets → '{new_col}'."
    except Exception:
        df[new_col] = pd.cut(num, bins=num_bins).astype(str)
        return df, f"Binned '{col}' into {num_bins} equal-width bins → '{new_col}'."


# ── Handler dispatch table ────────────────────────────────────────────────────

_HANDLERS = {
    "drop_column":                  _handle_drop_column,
    "rename_column":                _handle_rename_column,
    "move_column_front":            _handle_move_front,
    "move_column_end":              _handle_move_end,
    "drop_constant_column":         _handle_drop_constant,
    "keep_only_columns":            _handle_keep_only_columns,
    "normalize_missing_placeholders": _handle_normalize_missing,
    "handle_infinity":              _handle_handle_infinity,
    "normalize_blank":              _handle_normalize_blank,
    "impute_mean":                  _handle_impute_mean,
    "impute_median":                _handle_impute_median,
    "impute_mode":                  _handle_impute_mode,
    "impute_zero":                  _handle_impute_zero,
    "impute_custom":                _handle_impute_custom,
    "drop_null_rows":               _handle_drop_null_rows,
    "drop_null_rows_column":        _handle_drop_null_rows_column,
    "drop_duplicates_full":         _handle_drop_duplicates_full,
    "drop_duplicates_by_columns":   _handle_drop_duplicates_by_columns,
    "uppercase":                    _handle_uppercase,
    "lowercase":                    _handle_lowercase,
    "titlecase":                    _handle_titlecase,
    "strip_whitespace":             _handle_strip_whitespace,
    "remove_punctuation":           _handle_remove_punctuation,
    "remove_html":                  _handle_remove_html,
    "remove_stopwords":             _handle_remove_stopwords,
    "string_length":                _handle_string_length,
    "extract_digits":               _handle_extract_digits,
    "extract_email":                _handle_extract_email,
    "extract_phone":                _handle_extract_phone,
    "split_column":                 _handle_split_column,
    "concat_column":                _handle_concat_column,
    "replace_value_exact":          _handle_replace_value_exact,
    "replace_value_substring":      _handle_replace_value_substring,
    "replace_value_regex":          _handle_replace_value_regex,
    "one_hot_encode":               _handle_one_hot_encode,
    "ordinal_encode":               _handle_ordinal_encode,
    "frequency_encode":             _handle_frequency_encode,
    "label_encode":                 _handle_label_encode,
    "normalize_boolean":            _handle_normalize_boolean,
    "convert_percentage":           _handle_convert_percentage,
    "parse_accounting_currency":    _handle_parse_accounting_currency,
    "remove_currency_symbol":       _handle_remove_currency_symbol,
    "normalize_minmax":             _handle_normalize_minmax,
    "standardize_zscore":           _handle_standardize_zscore,
    "log_transform":                _handle_log_transform,
    "round_values":                 _handle_round_values,
    "convert_datatype":             _handle_convert_datatype,
    "convert_unit":                 _handle_convert_unit,
    "derived_math":                 _handle_derived_math,
    "extract_year":                 _handle_extract_year,
    "extract_month":                _handle_extract_month,
    "extract_day":                  _handle_extract_day,
    "extract_weekday":              _handle_extract_weekday,
    "extract_quarter":              _handle_extract_quarter,
    "extract_hour":                 _handle_extract_hour,
    "extract_minute":               _handle_extract_minute,
    "extract_weekend":              _handle_extract_weekend,
    "days_since":                   _handle_days_since,
    "date_difference":              _handle_date_difference,
    "standardize_datetime":         _handle_standardize_datetime,
    "clip_iqr":                     _handle_clip_iqr,
    "drop_iqr_rows":                _handle_drop_iqr_rows,
    "clip_percentile":              _handle_clip_percentile,
    "filter_rows":                  _handle_filter_rows,
    "remove_rows":                  _handle_remove_rows,
    "explode_column":               _handle_explode_column,
    "bin_column":                   _handle_bin_column,
}


# ── Public API ────────────────────────────────────────────────────────────────

def execute_plan(plan: list, df: pd.DataFrame) -> dict:
    """
    Execute a validated cleaning plan against the dataframe.

    Args:
        plan: list of operation dicts from intent_parser (pre-validated).
        df:   the pandas DataFrame to clean.

    Returns:
        {
            "df": cleaned DataFrame,
            "audit_log": list of per-operation audit entries,
            "warnings": list of warning strings,
            "errors":   list of error strings,
        }
    """
    audit_log = []
    warnings = []
    errors = []

    for op_dict in plan:
        operation = op_dict.get("operation", "")
        col = op_dict.get("column", "")
        parameters = op_dict.get("parameters", {})
        raw_step = op_dict.get("raw_step", "")

        # No-ops: log and continue, never modify df
        if operation in _NOOP_OPERATIONS:
            audit_log.append(make_operation_log(
                column=col or "",
                operation=operation,
                parameters=parameters,
                rows_before=len(df),
                rows_after=len(df),
                null_before=int(df[col].isnull().sum()) if col and col in df.columns else 0,
                null_after=int(df[col].isnull().sum()) if col and col in df.columns else 0,
                status="skipped",
                message=op_dict.get("message", f"No-op: '{operation}' on '{col}'."),
            ))
            if operation in ("unsupported", "ambiguous_instruction", "ambiguous_column"):
                warnings.append(op_dict.get("message", f"Skipped: {operation} for '{col}'."))
            continue

        # Snapshot before
        rows_before = len(df)
        null_before = int(df[col].isnull().sum()) if col and col in df.columns else 0

        handler = _HANDLERS.get(operation)
        if not handler:
            # Truly unknown operation — log and skip, never impute
            msg = (f"No handler registered for operation '{operation}' on '{col}'. "
                   "Step skipped. No data was modified.")
            logging.warning(msg)
            warnings.append(msg)
            audit_log.append(make_operation_log(
                column=col or "", operation=operation, parameters=parameters,
                rows_before=rows_before, rows_after=rows_before,
                null_before=null_before, null_after=null_before,
                status="skipped", message=msg,
            ))
            continue

        with OperationTimer() as timer:
            try:
                df, message = handler(df, col, parameters)
                rows_after = len(df)
                null_after = int(df[col].isnull().sum()) if col and col in df.columns else 0
                audit_log.append(make_operation_log(
                    column=col or "",
                    operation=operation,
                    parameters=parameters,
                    rows_before=rows_before,
                    rows_after=rows_after,
                    null_before=null_before,
                    null_after=null_after,
                    status="success",
                    message=message,
                    execution_time_ms=timer.elapsed_ms,
                ))
                logging.info(f"[executor] {operation} on '{col}': {message}")

            except Exception as ex:
                err_msg = (f"Error executing '{operation}' on '{col}': {ex}. "
                           "Step skipped. Dataframe state preserved from before this step.")
                logging.error(err_msg, exc_info=True)
                errors.append(err_msg)
                audit_log.append(make_operation_log(
                    column=col or "", operation=operation, parameters=parameters,
                    rows_before=rows_before, rows_after=rows_before,
                    null_before=null_before, null_after=null_before,
                    status="failed", message=err_msg, error=str(ex),
                    execution_time_ms=timer.elapsed_ms,
                ))

    return {
        "df": df,
        "audit_log": audit_log,
        "warnings": warnings,
        "errors": errors,
    }
