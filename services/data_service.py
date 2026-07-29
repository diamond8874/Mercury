"""
Cleaning pipeline and background workers.

Stage order for one session::

    upload      -> run_background_profile   (services/profile_service.py)
    goal given  -> run_analysis_job         (recommendations, this module)
                -> run_background_process   (clean + charts, this module)

``run_analysis_job`` blocks on the profile handshake, so the user can submit
their goal at any point - even a millisecond after the upload finishes - and
the pipeline still runs in the correct order.
"""

import os
import json
import logging

import numpy as np
import pandas as pd

from utils.session_manager import load_session, save_session
from utils.helpers import parse_json_response
from utils.job_tracker import (
    _set_job_state,
    _update_job_progress,
    wait_for_profile,
)
from services.llm_provider import get_llm_client
from services.profile_service import (
    read_dataset,
    build_profile,
    compact_profile_for_llm,
)
from services.chart_service import (
    generate_ai_charts,
    generate_auto_charts,
    build_chart_payload,
)

# Name fragments that mark a column as an identifier or as personal data.
IDENTIFIER_HINTS = ("id", "uuid", "guid", "hash", "index", "key", "code")
PII_HINTS = ("name", "email", "phone", "address", "ssn", "passport", "postcode", "zip")
NOISE_HINTS = ("noise", "random", "system_", "unnamed", "temp_", "junk")


# ---------------------------------------------------------------------------
# Schema summary (kept for backwards compatibility with older callers)
# ---------------------------------------------------------------------------

def summarize_schema(df, max_samples=1):
    """Compact per-column summary. Superseded by ``profile_service.build_profile``."""
    schema_summary = []
    num_rows = len(df)
    for col in df.columns:
        nulls = int(df[col].isnull().sum())
        null_pct = round((nulls / num_rows) * 100, 1) if num_rows else 0.0
        samples = []
        if max_samples > 0:
            samples = [str(s) for s in df[col].dropna().head(max_samples).tolist()]
        schema_summary.append({
            "column_name": str(col),
            "data_type": str(df[col].dtype),
            "null_percentage": null_pct,
            "unique_values_count": int(df[col].nunique(dropna=True)),
            "sample_values": samples,
        })
    return schema_summary


# ---------------------------------------------------------------------------
# Offline recommendation engine
# ---------------------------------------------------------------------------

def _duplicate_column_map(df):
    """Map each duplicated column to the first column holding identical values."""
    duplicates = {}
    signatures = {}
    for col in df.columns:
        try:
            signature = pd.util.hash_pandas_object(df[col].astype(str), index=False).sum()
        except Exception:  # noqa: BLE001 - exotic dtypes
            continue
        if signature in signatures:
            duplicates[str(col)] = signatures[signature]
        else:
            signatures[signature] = str(col)
    return duplicates


def generate_mock_recommendations(df, goal, profile=None):
    """
    Deterministic KEEP / DROP / TRANSFORM plan.

    Used when no API key is configured, when the provider call fails, and by
    the test-suite via ``api_key="MOCK"``. Statistical signals from the profile
    take priority; name heuristics only break the remaining ties.
    """
    if profile is None:
        profile = build_profile(df)

    by_name = {c["name"]: c for c in profile["columns"]}
    duplicates = _duplicate_column_map(df)
    goal_lower = (goal or "").lower()

    recommendations = []
    for col in df.columns:
        name = str(col)
        lower = name.lower()
        stats = by_name.get(name, {})
        semantic = stats.get("semantic_type", "categorical")
        null_pct = stats.get("null_pct", 0.0)
        mentioned_in_goal = lower in goal_lower

        if stats.get("is_empty"):
            action, reason, transformation = (
                "drop", "Column is 100% empty - it carries no signal.", None)
        elif stats.get("is_constant"):
            action, reason, transformation = (
                "drop", "Single constant value across every row, so variance is zero.", None)
        elif name in duplicates:
            action, reason, transformation = (
                "drop", f"Exact duplicate of '{duplicates[name]}' - redundant features cause multicollinearity.", None)
        elif semantic == "identifier" and not mentioned_in_goal:
            action, reason, transformation = (
                "drop", f"Near-unique identifier ({stats.get('unique_pct', 0)}% distinct) with no predictive value.", None)
        elif any(hint in lower for hint in NOISE_HINTS) and not mentioned_in_goal:
            action, reason, transformation = (
                "drop", "Looks like a synthetic noise or scratch column rather than a real feature.", None)
        elif any(hint in lower for hint in PII_HINTS) and not mentioned_in_goal:
            action, reason, transformation = (
                "drop", "Personally identifiable information that does not help model training.", None)
        elif any(lower.endswith(hint) or lower.startswith(hint) or f"_{hint}" in lower
                 for hint in IDENTIFIER_HINTS) and not mentioned_in_goal and semantic != "numeric":
            action, reason, transformation = (
                "drop", "Identifier-style column, high cardinality and no correlation to the goal.", None)
        elif null_pct > 60:
            action, reason, transformation = (
                "drop", f"{null_pct}% of values are missing - imputation would invent most of the column.", None)
        elif semantic == "datetime":
            action, reason, transformation = (
                "transform", "Date values need parsing so chronological features can be derived.",
                "Convert to datetime object")
        elif semantic == "numeric" and null_pct > 0:
            action, reason, transformation = (
                "transform", f"Numeric column with {null_pct}% missing values needing imputation.",
                "Impute missing values using the column median")
        elif semantic in ("categorical", "boolean") and null_pct > 0:
            action, reason, transformation = (
                "transform", f"Categorical column with {null_pct}% missing values requiring imputation.",
                "Impute missing values with the most frequent category")
        elif semantic == "text":
            action, reason, transformation = (
                "drop", "Free-text column - it needs dedicated NLP features rather than tabular training.", None)
        elif mentioned_in_goal:
            action, reason, transformation = (
                "keep", "Explicitly referenced in your goal, so it is a direct feature or the target.", None)
        else:
            action, reason, transformation = (
                "keep", "Clean feature with usable variance and no missing values.", None)

        recommendations.append({
            "column": name,
            "action": action,
            "reason": reason,
            "transformation": transformation,
        })
    return recommendations


# ---------------------------------------------------------------------------
# LLM recommendation engine (provider-agnostic)
# ---------------------------------------------------------------------------

RECOMMENDATION_PROMPT = """You are a brilliant Data Scientist and AI cleaning agent.
The user wants to prepare a dataset for this specific goal:
"{goal}"

Here is the profiled dataset:
{profile}

Analyse each column and recommend whether to KEEP, DROP or TRANSFORM it.
Rules:
1. Drop columns that are empty, constant, duplicated, random identifiers/hashes,
   or clearly irrelevant to the goal.
2. Keep columns that are direct features, plausible targets, or strong context.
3. Transform columns needing date parsing, categorical encoding, numeric coercion,
   or imputation of missing values.
4. Give a short, educational reason for every decision.
5. Cover EVERY column in the profile exactly once, using its exact name.

Return valid JSON only, in this exact structure:
{{"recommendations": [{{"column": "column_name",
                        "action": "keep" | "drop" | "transform",
                        "reason": "Brief human-readable justification.",
                        "transformation": "Suggested transformation, or null for keep/drop"}}]}}"""


def generate_recommendations(llm, df, goal, profile=None):
    """
    Ask the configured provider for a cleaning plan.

    Returns ``(recommendations, source, warning)`` where source is ``"ai"`` or
    ``"offline"``. Any provider failure degrades to the deterministic engine
    rather than erroring out, so the pipeline always produces something usable.
    """
    if profile is None:
        profile = build_profile(df)

    if llm is None or not llm.is_live:
        note = None if (llm and llm.is_mock) else "No live API key configured - using the offline rule engine."
        return generate_mock_recommendations(df, goal, profile), "offline", note

    try:
        prompt = RECOMMENDATION_PROMPT.format(
            goal=goal,
            profile=json.dumps(compact_profile_for_llm(profile), indent=2, default=str)[:9000],
        )
        response = llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0, max_tokens=2000, json_mode=True,
        )
        parsed = parse_json_response(response)
        recommendations = parsed.get("recommendations", [])

        # Normalise, then fill in any column the model forgot.
        cleaned = []
        seen = set()
        valid_columns = {str(c) for c in df.columns}
        for item in recommendations:
            column = str(item.get("column", ""))
            if column not in valid_columns or column in seen:
                continue
            action = str(item.get("action", "keep")).lower().strip()
            if action not in ("keep", "drop", "transform"):
                action = "keep"
            seen.add(column)
            cleaned.append({
                "column": column,
                "action": action,
                "reason": str(item.get("reason") or "Recommended by the analysis model."),
                "transformation": item.get("transformation"),
            })

        if not cleaned:
            raise ValueError("Model returned no usable recommendations.")

        missing = [r for r in generate_mock_recommendations(df, goal, profile)
                   if r["column"] not in seen]
        cleaned.extend(missing)
        return cleaned, "ai", None

    except Exception as exc:  # noqa: BLE001 - never let a provider break the run
        logging.error(f"Recommendation call failed ({exc}); falling back to the offline engine.")
        return (generate_mock_recommendations(df, goal, profile), "offline",
                f"{llm.describe} was unavailable ({str(exc)[:160]}). Offline recommendations were used instead.")


def generate_mock_charts(df, goal=None):
    """Backwards-compatible alias for the deterministic chart planner."""
    return generate_auto_charts(df, goal)


# ---------------------------------------------------------------------------
# Shared cleaning logic
# ---------------------------------------------------------------------------

def apply_actions(df, actions):
    """
    Apply a KEEP/DROP/TRANSFORM plan to a DataFrame.

    Single source of truth for cleaning - both the synchronous ``/api/process``
    route and the background worker call this, so they can never drift apart.
    Returns ``(cleaned_df, stats)``.
    """
    initial_shape = df.shape
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]

    columns_to_drop = []
    transform_actions = []

    for col, col_data in (actions or {}).items():
        col = str(col).strip()
        if col not in df.columns:
            continue

        action = (col_data or {}).get("action", "keep")
        transformation = (col_data or {}).get("transformation") or ""
        hint = transformation.lower()

        if action == "drop":
            columns_to_drop.append(col)
            continue

        try:
            if action == "transform":
                if "date" in hint or "time" in hint:
                    df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
                elif any(k in hint for k in ("numeric", "number", "float", "int")):
                    df[col] = pd.to_numeric(df[col], errors="coerce")

                # Only an explicit encoding verb triggers encoding. Matching on
                # bare "categor"/"label" would fire on imputation instructions
                # such as "fill with the most frequent category".
                if any(k in hint for k in ("encode", "encoding", "one-hot", "onehot", "dummies")) \
                        and not pd.api.types.is_numeric_dtype(df[col]):
                    filled = df[col].fillna("Unknown").astype(str)
                    df[col] = filled.astype("category").cat.codes
                    transform_actions.append(f"Label-encoded '{col}'.")

            _impute(df, col)

            if action == "transform":
                transform_actions.append(
                    f"Transformed '{col}': {transformation or 'imputed missing values'}")
        except Exception as exc:  # noqa: BLE001 - a bad column must not abort cleaning
            logging.warning(f"Failed to transform column '{col}': {exc}")
            transform_actions.append(f"Failed to transform '{col}': {exc}")

    if columns_to_drop:
        df = df.drop(columns=columns_to_drop)

    final_shape = df.shape
    stats = {
        "initial_rows": int(initial_shape[0]),
        "initial_cols": int(initial_shape[1]),
        "final_rows": int(final_shape[0]),
        "final_cols": int(final_shape[1]),
        "dropped_columns": columns_to_drop,
        "transformations_applied": transform_actions,
    }
    return df, stats


def _impute(df, col):
    """Fill missing values with the median (numeric) or a sentinel (everything else)."""
    if not df[col].isnull().any():
        return
    if pd.api.types.is_numeric_dtype(df[col]):
        median = df[col].median()
        df[col] = df[col].fillna(median if pd.notna(median) else 0)
    elif pd.api.types.is_datetime64_any_dtype(df[col]):
        df[col] = df[col].ffill().bfill()
    else:
        mode = df[col].mode()
        df[col] = df[col].fillna(mode.iloc[0] if not mode.empty else "Unknown")


# ---------------------------------------------------------------------------
# Background worker: analysis (only runs once the user states a goal)
# ---------------------------------------------------------------------------

def run_analysis_job(app, session_id, goal, llm_opts=None, chain_process=True):
    """
    Thread worker for the analysis stage.

    Waits for background profiling, asks the configured model for a cleaning
    plan, then (by default) chains straight into cleaning + chart generation so
    a single goal submission produces the complete result.
    """
    llm_opts = llm_opts or {}
    with app.app_context():
        try:
            _set_job_state(session_id, "analyzing", phase="analyze", progress=5,
                           progress_msg="Waiting for the dataset profile...")

            if not wait_for_profile(session_id, timeout=180):
                logging.warning(f"Profile wait timed out for {session_id}; profiling inline.")

            session_data = load_session(session_id)
            if not session_data:
                _set_job_state(session_id, "error", phase="analyze", error="Session not found")
                return

            file_path = os.path.join(app.config['UPLOAD_FOLDER'], session_data.get("file_id", ""))
            if not os.path.exists(file_path):
                _set_job_state(session_id, "error", phase="analyze", error="Uploaded file not found")
                return

            sheet_name = session_data.get("sheet_name", "Default")
            df = read_dataset(file_path, session_data.get("file_type"), sheet_name)

            profile = session_data.get("profile")
            if not profile:
                _update_job_progress(session_id, 20, "Profiling the dataset...")
                profile = build_profile(df, sheet_name=sheet_name)
                session_data["profile"] = profile
                session_data["columns"] = profile["columns"]

            llm = get_llm_client(**llm_opts)
            _update_job_progress(session_id, 45, f"Consulting {llm.describe} for column recommendations...")

            recommendations, source, warning = generate_recommendations(llm, df, goal, profile)

            _update_job_progress(session_id, 85, "Saving the recommended schema plan...")
            session_data["goal"] = goal
            session_data["column_actions"] = {
                r["column"]: {"action": r["action"], "reason": r["reason"],
                              "transformation": r["transformation"]}
                for r in recommendations
            }
            session_data["analysis_source"] = source
            session_data["llm"] = llm.config.public_dict()

            dropped = [r["column"] for r in recommendations if r["action"] == "drop"]
            transformed = [r["column"] for r in recommendations if r["action"] == "transform"]
            session_data["chat_history"].append(
                {"role": "user", "content": f"My data cleaning goal is: {goal}"})
            session_data["chat_history"].append(
                {"role": "assistant", "content": _analysis_summary_message(
                    goal, profile, dropped, transformed, llm, warning)})
            save_session(session_data)

            result = {
                "recommendations": recommendations,
                "column_actions": session_data["column_actions"],
                "chat_history": session_data["chat_history"],
                "source": source,
                "llm": llm.config.public_dict(),
                "warning": warning,
            }
            _set_job_state(session_id, "analyze_done", phase="analyze", progress=100,
                           progress_msg="Recommendations ready.", result=result)
            logging.info(f"Analysis complete for session {session_id} (source={source})")

            if chain_process:
                run_background_process(app, session_id, llm_opts=llm_opts)

        except Exception as exc:  # noqa: BLE001
            logging.error(f"Analysis job failed for {session_id}: {exc}")
            _set_job_state(session_id, "error", phase="analyze", error=str(exc))


def _analysis_summary_message(goal, profile, dropped, transformed, llm, warning):
    """Human-readable chat summary of what the analysis stage decided."""
    shape = profile["shape"]
    lines = [
        f"Goal set: **{goal}**.",
        f"I read all **{shape['rows']} rows x {shape['cols']} columns** before analysing "
        f"({profile['missing_pct']}% of cells were missing"
        + (f", {profile['duplicate_rows']} duplicate rows" if profile["duplicate_rows"] else "") + ").",
    ]
    if dropped:
        preview = ", ".join(f"`{c}`" for c in dropped[:3])
        more = f" and {len(dropped) - 3} more" if len(dropped) > 3 else ""
        lines.append(f"I recommend dropping **{len(dropped)}** column(s): {preview}{more}.")
    if transformed:
        lines.append(f"**{len(transformed)}** column(s) will be transformed or imputed.")
    if profile["warnings"]:
        lines.append("Data-quality notes: " + " ".join(profile["warnings"][:3]))
    lines.append(f"Analysed with {llm.describe}. Cleaning and charts are running now - "
                 "override any decision in the grid and I will reprocess.")
    if warning:
        lines.append(f"⚠️ {warning}")
    return "<br>".join(lines)


# ---------------------------------------------------------------------------
# Background worker: cleaning + charts
# ---------------------------------------------------------------------------

def run_background_process(app, session_id, api_key=None, llm_opts=None):
    """
    Thread worker for the cleaning stage.

    Applies the session's current ``column_actions``, writes the cleaned Excel
    file, generates the chart plan, and stores everything on the session so a
    later reload restores the full dashboard.
    """
    llm_opts = dict(llm_opts or {})
    if api_key and not llm_opts.get("api_key"):
        llm_opts["api_key"] = api_key

    def _run():
        _set_job_state(session_id, "processing", phase="process", progress=10,
                       progress_msg="Reading the raw dataset...")
        session_data = load_session(session_id)
        if not session_data:
            _set_job_state(session_id, "error", phase="process", error="Session not found")
            return

        file_id = session_data.get("file_id")
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id or "")
        if not os.path.exists(file_path):
            _set_job_state(session_id, "error", phase="process", error="Uploaded file not found")
            return

        sheet_name = session_data.get("sheet_name", "Default")
        df = read_dataset(file_path, session_data.get("file_type"), sheet_name)

        _update_job_progress(session_id, 35, "Applying Keep / Drop / Transform rules...")
        cleaned_df, stats = apply_actions(df, session_data.get("column_actions", {}))

        _update_job_progress(session_id, 60, "Writing the cleaned dataset...")
        output_filename = f"cleaned_{str(file_id).split('.')[0]}.xlsx"
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        cleaned_df.to_excel(output_path, index=False)
        session_data["cleaned_filename"] = output_filename

        _update_job_progress(session_id, 75, "Designing visualisations for the cleaned data...")
        llm = get_llm_client(**llm_opts)
        chart_specs, chart_source = generate_ai_charts(
            llm, cleaned_df, session_data.get("goal"), max_charts=6)
        rendered_charts = build_chart_payload(cleaned_df, chart_specs)

        _update_job_progress(session_id, 92, "Compiling previews, statistics and the report payload...")
        preview_data = cleaned_df.head(10).fillna("").astype(object).map(_stringify).to_dict(orient="records")
        cleaned_profile = build_profile(cleaned_df, sheet_name=sheet_name, sample_rows=10)

        session_data["charts"] = chart_specs
        session_data["chart_source"] = chart_source
        session_data["cleaned_profile"] = cleaned_profile

        result_payload = {
            "download_url": f"/api/download/{output_filename}",
            "stats": stats,
            "charts": rendered_charts,
            "preview": preview_data,
            "chart_source": chart_source,
            "cleaned_profile": {
                "shape": cleaned_profile["shape"],
                "missing_pct": cleaned_profile["missing_pct"],
                "duplicate_rows": cleaned_profile["duplicate_rows"],
            },
        }
        session_data["bg_result"] = result_payload
        save_session(session_data)

        _set_job_state(session_id, "done", phase="process", result=result_payload,
                       progress=100, progress_msg="Done!")
        logging.info(f"Background processing complete for session {session_id} "
                     f"({len(rendered_charts)} charts, source={chart_source})")

    # ``run_background_process`` is called both from a fresh thread and from
    # inside ``run_analysis_job`` (which already holds an app context).
    try:
        if app is None:
            _run()
        else:
            with app.app_context():
                _run()
    except Exception as exc:  # noqa: BLE001
        logging.error(f"Background process error for {session_id}: {exc}")
        _set_job_state(session_id, "error", phase="process", error=str(exc))


def _stringify(value):
    """Keep preview payloads JSON-clean without losing readability."""
    if value is None:
        return ""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(float(value)) else round(float(value), 6)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value
