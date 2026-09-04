import os
import logging
import re
import difflib
import pandas as pd
import numpy as np
from utils.session_manager import load_session, save_session
from utils.job_tracker import _set_job_state, _update_job_progress
from services.cleaning import build_cleaning_plan, validate_plan, execute_plan


# Schema summarization helper for more compact AI prompts
def summarize_schema(df, max_samples=1):
    schema_summary = []
    num_rows = len(df)
    for col in df.columns:
        nulls = int(df[col].isnull().sum())
        null_pct = round((nulls / num_rows) * 100, 1) if num_rows else 0.0
        unique_count = int(df[col].nunique(dropna=True))
        samples = []
        if max_samples > 0:
            samples = df[col].dropna().head(max_samples).tolist()
            samples = [str(s) for s in samples]
        schema_summary.append({
            "column_name": col,
            "data_type": str(df[col].dtype),
            "null_percentage": null_pct,
            "unique_values_count": unique_count,
            "sample_values": samples
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

            _update_job_progress(session_id, 30, "Rebuilding dataset structure & applying Keep/Drop columns...")
            initial_shape = df.shape
            df.columns = df.columns.str.strip()

            initial_nulls = df.isnull().sum().to_dict()
            initial_duplicates = int(df.duplicated().sum())

            columns_to_drop = []
            transform_actions = []

            for col, col_data in actions.items():
                action = col_data.get('action')
                trans = col_data.get('transformation')
                if col not in df.columns:
                    continue
                if action == 'drop':
                    columns_to_drop.append(col)
                elif action == 'transform':
                    try:
                        df, msg = apply_column_transformation(df, col, trans)
                        transform_actions.append(msg)
                    except Exception as tex:
                        logging.warning(f"BG transform error {col}: {tex}")
                elif action == 'keep':
                    # Explicitly preserve column without modification
                    pass

            _update_job_progress(session_id, 55, "Running Pandas type transformations & data cleaning...")
            if columns_to_drop:
                df = df.drop(columns=columns_to_drop)

            final_shape = df.shape
            final_nulls = df.isnull().sum().to_dict()
            final_duplicates = int(df.duplicated().sum())

            # Save cleaned Excel
            output_filename = f"cleaned_{file_id.split('.')[0]}.xlsx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            df.to_excel(output_path, index=False)
            session_data["cleaned_filename"] = output_filename

            stats = {
                "initial_rows": initial_shape[0], "initial_cols": initial_shape[1],
                "final_rows": final_shape[0], "final_cols": final_shape[1],
                "dropped_columns": columns_to_drop,
                "transformations_applied": transform_actions,
                "null_before": sum(initial_nulls.values()),
                "null_after": sum(final_nulls.values()),
                "duplicate_before": initial_duplicates,
                "duplicate_after": final_duplicates
            }


            # Skip chart generation during background clean processing.
            charts = []
            session_data["charts"] = charts

            # Build rendered chart data
            rendered_charts = []
            for chart in charts:
                chart_type = chart.get("chart_type")
                title = chart.get("title")
                x_col = chart.get("x_axis")
                y_col = chart.get("y_axis")
                desc = chart.get("description")
                if x_col not in df.columns:
                    continue
                chart_item = {"chart_type": chart_type, "title": title, "description": desc,
                              "x_axis": x_col, "y_axis": y_col, "data": []}
                try:
                    if chart_type == 'histogram':
                        vc = df[x_col].value_counts().head(10)
                        chart_item["labels"] = [str(x) for x in vc.index]
                        chart_item["values"] = [int(v) for v in vc.values]
                    elif chart_type == 'pie':
                        vc = df[x_col].value_counts().head(6)
                        chart_item["labels"] = [str(x) for x in vc.index]
                        chart_item["values"] = [int(v) for v in vc.values]
                    elif chart_type == 'scatter' and y_col in df.columns:
                        tmp = df[[x_col, y_col]].dropna().head(100)
                        chart_item["points"] = [{"x": float(r[x_col]) if pd.api.types.is_numeric_dtype(df[x_col]) else str(r[x_col]),
                                                  "y": float(r[y_col]) if pd.api.types.is_numeric_dtype(df[y_col]) else str(r[y_col])} for _, r in tmp.iterrows()]
                    elif chart_type == 'line' and y_col in df.columns:
                        tmp = df[[x_col, y_col]].dropna().sort_values(by=x_col).head(50)
                        chart_item["labels"] = [str(x) for x in tmp[x_col]]
                        chart_item["values"] = [float(y) if pd.api.types.is_numeric_dtype(df[y_col]) else str(y) for y in tmp[y_col]]
                    elif chart_type == 'bar':
                        if y_col and y_col in df.columns:
                            if df[x_col].nunique() < 15:
                                grouped = df.groupby(x_col)[y_col].mean().head(15)
                                chart_item["labels"] = [str(x) for x in grouped.index]
                                chart_item["values"] = [float(v) for v in grouped.values]
                                chart_item["title"] = f"{title} (Avg)"
                            else:
                                tmp = df[[x_col, y_col]].dropna().head(15)
                                chart_item["labels"] = [str(x) for x in tmp[x_col]]
                                chart_item["values"] = [float(y) if pd.api.types.is_numeric_dtype(df[y_col]) else str(y) for y in tmp[y_col]]
                        else:
                            vc = df[x_col].value_counts().head(15)
                            chart_item["labels"] = [str(x) for x in vc.index]
                            chart_item["values"] = [int(v) for v in vc.values]
                    rendered_charts.append(chart_item)
                except Exception as cde:
                    logging.warning(f"BG chart data error {title}: {cde}")

            _update_job_progress(session_id, 95, "Compiling final table previews, statistics, and reports...")
            df_preview = df.head(10).copy().astype(object)
            df_preview = df_preview.where(pd.notnull(df_preview), "")
            preview_data = df_preview.to_dict(orient='records')

            result_payload = {
                "download_url": f"/api/download/{output_filename}",
                "stats": stats,
                "charts": rendered_charts,
                "preview": preview_data,
            }
            session_data.setdefault("bg_result", {})
            session_data["bg_result"] = result_payload
            save_session(session_data)

            _set_job_state(session_id, "done", result=result_payload, progress=100, progress_msg="Done!")
            logging.info(f"Background process complete for session {session_id}")

        except Exception as ex:
            logging.error(f"Background process error for {session_id}: {ex}")
            _set_job_state(session_id, "error", error=str(ex))
