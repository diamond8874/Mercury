import os
import logging
import re
import difflib
import pandas as pd
import numpy as np
from utils.session_manager import load_session, save_session
from utils.job_tracker import _set_job_state, _update_job_progress
from services.cleaning import build_cleaning_plan, validate_plan, execute_plan, run_cleaning_engine


# Schema summarization helper with prompt size caps (max columns, max samples, max length)
def summarize_schema(df, max_samples=1, max_columns=50, max_val_chars=120):
    schema_summary = []
    num_rows = len(df)
    cols_to_process = list(df.columns)[:max_columns]
    effective_samples = min(max(max_samples, 0), 3)

    for col in cols_to_process:
        nulls = int(df[col].isnull().sum())
        null_pct = round((nulls / num_rows) * 100, 1) if num_rows else 0.0
        unique_count = int(df[col].nunique(dropna=True))
        samples = []
        if effective_samples > 0:
            raw_samples = df[col].dropna().head(effective_samples).tolist()
            # Wrap truncated sample values in delimiters to defend against prompt injection and excessive payload
            samples = [
                f"<untrusted_sample_value>{str(s)[:max_val_chars]}</untrusted_sample_value>"
                for s in raw_samples
            ]
        schema_summary.append({
            "column_name": col,
            "data_type": str(df[col].dtype),
            "null_percentage": null_pct,
            "unique_values_count": unique_count,
            "sample_values": samples
        })

    if len(df.columns) > max_columns:
        omitted = len(df.columns) - max_columns
        schema_summary.append({
            "column_name": f"[... {omitted} additional columns omitted for prompt brevity]",
            "data_type": "N/A",
            "null_percentage": 0.0,
            "unique_values_count": 0,
            "sample_values": []
        })

    return schema_summary

# Mock AI Recommendations Fallback
def generate_mock_recommendations(df, goal):
    recommendations = []
    goal_lower = (goal or "").lower()

    # Exclude global phrases like "remove duplicates", "remove nulls" from triggering column drops
    clean_goal_for_drop = re.sub(
        r'\b(remove|drop|delete)\s+(duplicates?|nulls?|nans?|missing|rows?|placeholders?|outliers?|invalid|bad)\b',
        '',
        goal_lower,
        flags=re.IGNORECASE
    )

    for col in df.columns:
        col_lower = col.lower()
        col_spaced = col_lower.replace('_', ' ')
        col_pattern = rf"\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b"

        # Explicit column mention check
        has_col_mention = bool(re.search(col_pattern, clean_goal_for_drop))

        user_wants_drop = False
        if has_col_mention:
            drop_verb_pattern = rf"\b(?:drop|remove|delete|omit|eliminate)\b.*\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b|\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b.*\b(?:drop|remove|delete|omit|eliminate)\b"
            user_wants_drop = bool(re.search(drop_verb_pattern, clean_goal_for_drop))

        user_wants_keep = has_col_mention and any(kw in goal_lower for kw in ["keep", "retain", "include", "save"])
        user_wants_trans = has_col_mention and any(kw in goal_lower for kw in ["transform", "tranform", "convert", "replace", "change", "impute", "->", "=>"])

        if user_wants_drop:
            action = "drop"
            reason = f"Explicitly requested to drop column '{col}' based on user goal."
            trans = None
        elif user_wants_trans:
            action = "transform"
            reason = f"Explicitly requested transformation for column '{col}' in goal prompt."
            trans = goal
        elif user_wants_keep:
            action = "keep"
            reason = f"Explicitly requested to keep column '{col}' based on user goal."
            trans = None
        elif df[col].isnull().all():
            action = "drop"
            reason = "Column contains 100% missing values."
            trans = None
        else:
            action = "keep"
            reason = "Retained column by default. Will only modify if requested."
            trans = None

        recommendations.append({
            "column": col,
            "action": action,
            "reason": reason,
            "transformation": trans
        })
    return recommendations


def generate_mock_charts(df):
    final_cols = list(df.columns)
    charts = []
    if "Age" in final_cols:
        charts.append({
            "chart_type": "histogram",
            "title": "Distribution of Age in Cleaned Dataset",
            "x_axis": "Age",
            "y_axis": None,
            "description": "Visualizes the distribution of age to check for skewness and sample representation."
        })
    if "Monthly_Subscription_Fee" in final_cols:
        y_col = "Monthly_Subscription_Fee"
        x_col = "Churned_Status" if "Churned_Status" in final_cols else final_cols[0]
        charts.append({
            "chart_type": "bar",
            "title": "Average Subscription Fee by Churn Status",
            "x_axis": x_col,
            "y_axis": y_col,
            "description": "Compares subscription fee rates between churned and retained customers."
        })
    if "Gender" in final_cols:
        charts.append({
            "chart_type": "pie",
            "title": "Gender Distribution of Customers",
            "x_axis": "Gender",
            "y_axis": None,
            "description": "Shows the breakdown of customers by gender category."
        })
    return charts

import difflib

def match_column_name(target_col: str, text: str) -> bool:
    """
    Smart fuzzy column matcher that detects column names in user prompts
    even with UK/US spelling differences (behavioural vs behavioral), 
    singular/plural variations, spaces vs underscores, typos, or partial phrases.
    """
    if not target_col or not text:
        return False

    col_lower = target_col.lower()
    col_clean = re.sub(r'[^a-z0-9]', '', col_lower)
    text_lower = text.lower()
    text_clean = re.sub(r'[^a-z0-9]', ' ', text_lower)

    # 1. Direct or clean string substring match
    if col_lower in text_lower or col_clean in re.sub(r'[^a-z0-9]', '', text_lower):
        return True

    # 2. Word & N-gram fuzzy matching
    words = [re.sub(r'[^a-z0-9]', '', w) for w in text_clean.split() if len(w) > 2]
    if not words:
        return False

    # Single word fuzzy match (ratio >= 0.78)
    for w in words:
        if difflib.SequenceMatcher(None, col_clean, w).ratio() >= 0.78:
            return True

    # N-gram fuzzy match (ratio >= 0.70)
    ngrams = []
    for i in range(len(words) - 1):
        ngrams.append(words[i] + words[i+1])
    for i in range(len(words) - 2):
        ngrams.append(words[i] + words[i+1] + words[i+2])

    for ng in ngrams:
        if difflib.SequenceMatcher(None, col_clean, ng).ratio() >= 0.70:
            return True

    return False

def polish_and_standardize_prompt(raw_prompt: str, df_columns=None) -> str:
    """
    AI Prompt Polish & Intent Standardizer Module.
    Polishes raw, typo-ridden, or informal user prompts into clean, 
    canonical instructions before execution.
    """
    if not raw_prompt or not isinstance(raw_prompt, str):
        return ""

    polished = raw_prompt.strip()

    # 1. Common Typo & Slang Corrections
    typo_map = {
        r'\btranform\b': 'transform',
        r'\bperfrom\b': 'perform',
        r'\btranformation\b': 'transformation',
        r'\bcolum\b': 'column',
        r'\bcolums\b': 'columns',
        r'\breove\b': 'remove',
        r'\bdelte\b': 'delete',
        r'\bupcase\b': 'uppercase',
        r'\blowcase\b': 'lowercase',
        r'\bnul\b': 'null',
        r'\bdups\b': 'duplicates',
        r'\bduplicats\b': 'duplicates'
    }
    for typo_pattern, correction in typo_map.items():
        polished = re.sub(typo_pattern, correction, polished, flags=re.IGNORECASE)

    # 2. Standardize Arrow Shorthand Notation (only for pure shorthand pairs like "0 -> No", not full natural prompts)
    if not re.search(r'\b(?:transform|replace|change|convert)\b', polished, re.IGNORECASE):
        polished = re.sub(
            r"(?<!\bcolumn\s)(?<!\bcol\s)['\"]?(\b[a-zA-Z0-9_.\-\$]+\b)['\"]?\s*(?:->|=>|=)\s*['\"]?(\b[a-zA-Z0-9_.\-\$]+\b)['\"]?",
            r"where \1 replace \2",
            polished,
            flags=re.IGNORECASE
        )

    # 3. Match column names case-insensitively if DataFrame columns provided
    if df_columns is not None:
        for c in df_columns:
            if match_column_name(c, polished):
                # Replace fuzzy matches with exact column name if needed
                pass

    return polished

def apply_column_transformation(df, col, trans, dry_run=False):
    """
    Executes advanced, versatile column transformations specified by AI or user prompts
    using the safe, structured services.cleaning engine.
    """
    raw_trans = str(trans or "").strip()
    if not raw_trans:
        return df, f"No transformation specified for '{col}'"

    # Match column if passed
    if col and col not in df.columns:
        matched = [c for c in df.columns if c.lower() == str(col).lower()]
        if matched:
            col = matched[0]
        else:
            return df, f"Column '{col}' not found in dataset"

    plan = build_cleaning_plan(col, raw_trans, df)
    val_results = validate_plan(plan, df)

    errors = [r["message"] for r in val_results if r["status"] == "error"]
    if errors:
        return df, f"Validation failed for '{col}': " + " | ".join(errors)

    if dry_run:
        return df, plan

    res = execute_plan(plan, df)
    cleaned_df = res["df"]
    msgs = [item["message"] for item in res["audit_log"] if item.get("message")]
    if res.get("warnings"):
        msgs.extend(res["warnings"])
    if res.get("errors"):
        msgs.extend(res["errors"])

    final_msg = " | ".join(msgs) if msgs else f"No operations executed for '{col}'"
    return cleaned_df, final_msg



def run_background_process(app, session_id, api_key=None):
    """
    Re-runs the full pandas cleaning + chart generation pipeline using the
    session's current column_actions. Saves results to the session JSON so
    the frontend /status poll can pick them up.
    """
    with app.app_context():
        try:
            _set_job_state(session_id, "processing", progress=10, progress_msg="Reading raw Excel/CSV dataset...")
            session_data = load_session(session_id)
            if not session_data:
                _set_job_state(session_id, "error", error="Session not found")
                return

            file_id = session_data.get("file_id")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file_id)
            if not os.path.exists(file_path):
                _set_job_state(session_id, "error", error="Uploaded file not found")
                return

            actions = session_data.get("column_actions", {})
            sheet_name = session_data.get("sheet_name", 0)

            # Load file
            file_ext = file_id.rsplit('.', 1)[1].lower()
            if file_ext in ['xlsx', 'xls']:
                df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name not in ("Default", None) else 0)
            else:
                df = pd.read_csv(file_path)

            _update_job_progress(session_id, 35, "Running unified cleaning engine (Pydantic schema & transforms)...")
            
            clean_res = run_cleaning_engine(df, actions)
            df = clean_res["df"]
            stats = clean_res["stats"]
            audit_log = clean_res["audit_log"]
            quality_metrics = clean_res["quality_metrics"]

            _update_job_progress(session_id, 75, "Saving cleaned dataset output...")
            output_filename = f"cleaned_{session_id}.xlsx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            df.to_excel(output_path, index=False)
            session_data["cleaned_filename"] = output_filename
            session_data["audit_log"] = audit_log
            session_data["quality_metrics"] = quality_metrics
            session_data["stats"] = stats

            # Skip chart generation during background clean processing.
            charts = []
            session_data["charts"] = charts
            rendered_charts = []

            _update_job_progress(session_id, 95, "Compiling final table previews, statistics, and reports...")
            df_preview = df.head(10).copy().astype(object)
            df_preview = df_preview.where(pd.notnull(df_preview), "")
            preview_data = df_preview.to_dict(orient='records')

            result_payload = {
                "download_url": f"/api/download/{output_filename}",
                "stats": stats,
                "charts": rendered_charts,
                "preview": preview_data,
                "quality_metrics": quality_metrics,
                "audit_log": audit_log,
            }
            session_data.setdefault("bg_result", {})
            session_data["bg_result"] = result_payload
            session_data["preview"] = preview_data
            session_data["row_count"] = df.shape[0]
            session_data["col_count"] = df.shape[1]
            session_data["status"] = "done"
            save_session(session_data)

            _set_job_state(session_id, "done", result=result_payload, progress=100, progress_msg="Done!")
            logging.info(f"Background process complete for session {session_id}")
            return result_payload

        except Exception as ex:
            logging.error(f"Background process error for {session_id}: {ex}")
            _set_job_state(session_id, "error", error=str(ex))
            raise

