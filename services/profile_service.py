"""
Dataset profiling - the "read the data first" stage.

Nothing in here talks to an LLM. As soon as a file lands we compute a full
statistical picture of it in a background thread while the user is still
typing their goal. When the goal arrives the analysis stage reuses this
profile instead of re-reading the file, so the AI step starts instantly.
"""

import os
import logging
import datetime
import warnings

import numpy as np
import pandas as pd

from utils.session_manager import load_session, save_session
from utils.job_tracker import (
    _set_job_state,
    _update_job_progress,
    mark_profile_ready,
    clear_profile_ready,
)

# A column whose unique-ratio is above this is treated as a row identifier.
IDENTIFIER_UNIQUE_RATIO = 0.95
# Above this many distinct values a column stops being "categorical".
MAX_CATEGORICAL_CARDINALITY = 25


def read_dataset(file_path, file_ext=None, sheet_name=None):
    """Load a CSV/Excel file into a DataFrame, honouring the selected sheet."""
    file_ext = (file_ext or os.path.splitext(file_path)[1].lstrip('.')).lower()
    if file_ext in ("xlsx", "xls"):
        target = 0 if sheet_name in (None, "", "Default") else sheet_name
        return pd.read_excel(file_path, sheet_name=target)
    return pd.read_csv(file_path)


def _looks_like_dates(non_null, sample_size=30, threshold=0.8):
    """True when most sampled string values parse as dates."""
    sample = non_null.astype(str).head(sample_size)
    # Cheap pre-filter: a date needs digits plus a separator. Without this,
    # pandas happily coerces things like "12" or "Male" and we get false hits.
    plausible = sample.str.contains(r"\d", regex=True) & sample.str.contains(r"[-/:. ]", regex=True)
    if plausible.mean() < threshold:
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            parsed = pd.to_datetime(sample, errors="coerce")
        except (ValueError, TypeError, OverflowError):
            return False
    return parsed.notna().mean() > threshold


def _semantic_type(series):
    """Classify a column beyond its raw dtype."""
    non_null = series.dropna()
    if non_null.empty:
        return "empty"
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    if pd.api.types.is_numeric_dtype(series):
        if non_null.nunique() <= 2:
            return "boolean"
        return "numeric"

    # Dates that arrived as strings still deserve the datetime label. This is
    # checked before the identifier heuristic, because a date column is
    # naturally near-unique and would otherwise be written off as an id.
    if _looks_like_dates(non_null):
        return "datetime"

    unique_ratio = non_null.nunique() / len(non_null)
    if unique_ratio >= IDENTIFIER_UNIQUE_RATIO and len(non_null) > 10:
        return "identifier"

    if non_null.nunique() <= MAX_CATEGORICAL_CARDINALITY:
        return "categorical"

    avg_len = non_null.astype(str).str.len().mean()
    return "text" if avg_len > 40 else "categorical"


def _json_safe(value):
    """Convert numpy/pandas scalars into something ``json.dumps`` accepts."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(float(value)) else round(float(value), 4)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime.datetime, datetime.date)):
        return value.isoformat()
    if pd.isna(value) if np.isscalar(value) else False:
        return None
    return value


def profile_column(series, name, total_rows):
    """Build the per-column statistics block."""
    null_count = int(series.isnull().sum())
    non_null = series.dropna()
    unique_count = int(non_null.nunique())
    semantic = _semantic_type(series)

    column = {
        "name": name,
        "type": str(series.dtype),
        "semantic_type": semantic,
        "null_count": null_count,
        "null_pct": round((null_count / total_rows) * 100, 2) if total_rows else 0.0,
        "unique_count": unique_count,
        "unique_pct": round((unique_count / total_rows) * 100, 2) if total_rows else 0.0,
        "is_constant": unique_count <= 1,
        "is_empty": null_count == total_rows,
        "sample_values": [_json_safe(v) for v in non_null.head(3).tolist()],
    }

    if semantic in ("numeric", "boolean") and pd.api.types.is_numeric_dtype(series) and not non_null.empty:
        described = non_null.astype(float)
        column["stats"] = {
            "min": _json_safe(described.min()),
            "max": _json_safe(described.max()),
            "mean": _json_safe(described.mean()),
            "median": _json_safe(described.median()),
            "std": _json_safe(described.std()),
            "skew": _json_safe(described.skew()) if len(described) > 2 else None,
            "zeros": int((described == 0).sum()),
            "negatives": int((described < 0).sum()),
        }
        if len(described) > 8:
            q1, q3 = described.quantile(0.25), described.quantile(0.75)
            iqr = q3 - q1
            outliers = int(((described < q1 - 1.5 * iqr) | (described > q3 + 1.5 * iqr)).sum())
            column["stats"]["outliers"] = outliers

    if semantic in ("categorical", "boolean", "identifier", "text") and not non_null.empty:
        top = non_null.astype(str).value_counts().head(8)
        column["top_values"] = [
            {"value": str(idx), "count": int(cnt)} for idx, cnt in top.items()
        ]

    return column


def build_profile(df, sheet_name=None, sample_rows=8):
    """Compute the complete dataset profile used by the UI, AI and charts."""
    total_rows, total_cols = df.shape
    columns = [profile_column(df[col], str(col), total_rows) for col in df.columns]

    numeric_cols = [c["name"] for c in columns if c["semantic_type"] == "numeric"]
    categorical_cols = [c["name"] for c in columns if c["semantic_type"] in ("categorical", "boolean")]
    datetime_cols = [c["name"] for c in columns if c["semantic_type"] == "datetime"]
    identifier_cols = [c["name"] for c in columns if c["semantic_type"] == "identifier"]

    # Correlation pairs, strongest first.
    correlations = []
    numeric_frame = df[numeric_cols].apply(pd.to_numeric, errors="coerce") if numeric_cols else pd.DataFrame()
    if numeric_frame.shape[1] >= 2:
        try:
            matrix = numeric_frame.corr(numeric_only=True)
            seen = set()
            for x in matrix.columns:
                for y in matrix.columns:
                    if x == y or (y, x) in seen:
                        continue
                    seen.add((x, y))
                    value = matrix.loc[x, y]
                    if pd.notna(value):
                        correlations.append({"x": str(x), "y": str(y), "r": round(float(value), 4)})
            correlations.sort(key=lambda item: abs(item["r"]), reverse=True)
            correlations = correlations[:15]
        except Exception as exc:  # noqa: BLE001 - correlation is best-effort
            logging.warning(f"Correlation computation skipped: {exc}")

    duplicate_rows = 0
    try:
        duplicate_rows = int(df.duplicated().sum())
    except (TypeError, ValueError):
        pass  # unhashable cell types

    total_cells = total_rows * total_cols
    missing_cells = int(df.isnull().sum().sum())

    warnings = []
    for column in columns:
        if column["is_empty"]:
            warnings.append(f"'{column['name']}' is completely empty.")
        elif column["null_pct"] > 40:
            warnings.append(f"'{column['name']}' is {column['null_pct']}% missing.")
        if column["is_constant"] and not column["is_empty"]:
            warnings.append(f"'{column['name']}' holds a single constant value.")
    if duplicate_rows:
        warnings.append(f"{duplicate_rows} duplicate row(s) detected.")

    return {
        "generated_at": datetime.datetime.now().isoformat(),
        "sheet_name": sheet_name or "Default",
        "shape": {"rows": int(total_rows), "cols": int(total_cols)},
        "memory_bytes": int(df.memory_usage(deep=True).sum()),
        "duplicate_rows": duplicate_rows,
        "missing_cells": missing_cells,
        "missing_pct": round((missing_cells / total_cells) * 100, 2) if total_cells else 0.0,
        "columns": columns,
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "datetime_columns": datetime_cols,
        "identifier_columns": identifier_cols,
        "correlations": correlations,
        "warnings": warnings[:12],
        "preview": df.head(sample_rows).fillna("").astype(object).map(_json_safe).to_dict(orient="records"),
    }


def compact_profile_for_llm(profile, max_columns=60):
    """Trim the profile down to what is worth spending prompt tokens on."""
    compact = {
        "rows": profile["shape"]["rows"],
        "columns": profile["shape"]["cols"],
        "duplicate_rows": profile["duplicate_rows"],
        "missing_pct": profile["missing_pct"],
        "top_correlations": profile["correlations"][:6],
        "schema": [],
    }
    for column in profile["columns"][:max_columns]:
        entry = {
            "name": column["name"],
            "dtype": column["type"],
            "kind": column["semantic_type"],
            "null_pct": column["null_pct"],
            "unique": column["unique_count"],
            "samples": column["sample_values"][:2],
        }
        stats = column.get("stats")
        if stats:
            entry["range"] = [stats.get("min"), stats.get("max")]
            entry["mean"] = stats.get("mean")
        top_values = column.get("top_values")
        if top_values:
            entry["top"] = [tv["value"] for tv in top_values[:4]]
        compact["schema"].append(entry)
    return compact


def run_background_profile(app, session_id, sheet_name=None):
    """
    Thread worker: read + profile the dataset immediately after upload.

    Runs while the user is still typing their goal, so the analysis stage
    never has to wait on file I/O.
    """
    with app.app_context():
        try:
            clear_profile_ready(session_id)
            _set_job_state(session_id, "profiling", phase="profile", progress=8,
                           progress_msg="Reading the uploaded dataset...")

            session_data = load_session(session_id)
            if not session_data:
                _set_job_state(session_id, "error", phase="profile", error="Session not found")
                return

            file_id = session_data.get("file_id")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
            if not os.path.exists(file_path):
                _set_job_state(session_id, "error", phase="profile", error="Uploaded file not found")
                return

            sheet_name = sheet_name or session_data.get("sheet_name") or "Default"
            df = read_dataset(file_path, session_data.get("file_type"), sheet_name)

            _update_job_progress(session_id, 45, "Profiling column types, nulls and distributions...")
            profile = build_profile(df, sheet_name=sheet_name)

            _update_job_progress(session_id, 80, "Scoring correlations and data-quality warnings...")
            session_data["profile"] = profile
            session_data["columns"] = profile["columns"]
            session_data["row_count"] = profile["shape"]["rows"]
            session_data["col_count"] = profile["shape"]["cols"]
            session_data["preview"] = profile["preview"]
            session_data["sheet_name"] = sheet_name
            save_session(session_data)

            summary = {
                "shape": profile["shape"],
                "missing_pct": profile["missing_pct"],
                "duplicate_rows": profile["duplicate_rows"],
                "numeric_columns": profile["numeric_columns"],
                "categorical_columns": profile["categorical_columns"],
                "datetime_columns": profile["datetime_columns"],
                "warnings": profile["warnings"],
            }
            _set_job_state(session_id, "profile_ready", phase="profile", progress=100,
                           progress_msg="Dataset read and profiled - waiting for your goal.",
                           result={"profile_summary": summary})
            mark_profile_ready(session_id)
            logging.info(f"Profiling complete for session {session_id}")

        except Exception as exc:  # noqa: BLE001 - worker must never die silently
            logging.error(f"Profiling failed for {session_id}: {exc}")
            _set_job_state(session_id, "error", phase="profile", error=str(exc))
            mark_profile_ready(session_id)  # unblock any waiting analysis thread
