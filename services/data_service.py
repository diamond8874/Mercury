import os
import logging
import pandas as pd
import numpy as np
from utils.session_manager import load_session, save_session
from utils.job_tracker import _set_job_state, _update_job_progress

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
    for col in df.columns:
        col_lower = col.lower()
        if "id" in col_lower or "hash" in col_lower:
            action = "drop"
            reason = f"Useless random identifier. High cardinality and zero correlation to goal '{goal}'."
            trans = None
        elif "name" in col_lower:
            action = "drop"
            reason = "Personally identifiable information (PII) that doesn't aid model training."
            trans = None
        elif "noise" in col_lower or "system" in col_lower:
            action = "drop"
            reason = "Synthetic noise column representing non-predictive random signals."
            trans = None
        elif "empty" in col_lower or "null" in col_lower:
            action = "drop"
            reason = "Empty column with 100% missing values."
            trans = None
        elif "duplicated" in col_lower:
            action = "drop"
            reason = "Duplicate copy of fee column. Redundant features cause multicollinearity."
            trans = None
        elif "date" in col_lower:
            action = "transform"
            reason = "Date string needs to be parsed to allow extraction of chronological metrics like tenure."
            trans = "Convert to datetime object"
        elif col_lower in ["gender", "sex"]:
            action = "transform"
            reason = "Categorical string column with missing values. Requires imputation and label encoding."
            trans = "Impute missing with mode and label encode"
        elif col_lower in ["age", "income"]:
            action = "transform"
            reason = "Numeric column containing missing values that need numerical imputation."
            trans = "Impute missing values using column median"
        elif col_lower in ["churn", "churned", "churned_status", "status"]:
            action = "keep"
            reason = "Direct target label representing the classification outcome."
            trans = None
        else:
            action = "keep"
            reason = "Key numerical or categorical feature directly relevant to predicting user behavior."
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
                        if trans and ('date' in trans.lower() or 'time' in trans.lower()):
                            df[col] = pd.to_datetime(df[col], errors='coerce')
                        elif trans and any(k in trans.lower() for k in ['numeric', 'number', 'float', 'int']):
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                            if any(k in trans.lower() for k in ['impute', 'fill', 'missing']):
                                df[col] = df[col].fillna(df[col].median())
                        elif pd.api.types.is_numeric_dtype(df[col]):
                            if df[col].isnull().any():
                                df[col] = df[col].fillna(df[col].median())
                        else:
                            if df[col].isnull().any():
                                df[col] = df[col].fillna("Unknown")
                        transform_actions.append(f"Transformed '{col}': {trans or 'imputed'}")
                    except Exception as tex:
                        logging.warning(f"BG transform error {col}: {tex}")
                else:
                    try:
                        if pd.api.types.is_numeric_dtype(df[col]):
                            if df[col].isnull().any():
                                df[col] = df[col].fillna(df[col].median())
                        else:
                            if df[col].isnull().any():
                                df[col] = df[col].fillna("Unknown")
                    except Exception:
                        pass

            _update_job_progress(session_id, 55, "Running Pandas type transformations & data cleaning...")
            if columns_to_drop:
                df = df.drop(columns=columns_to_drop)

            final_shape = df.shape

            # Save cleaned Excel
            output_filename = f"cleaned_{file_id.split('.')[0]}.xlsx"
            output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
            df.to_excel(output_path, index=False)
            session_data["cleaned_filename"] = output_filename

            stats = {
                "initial_rows": initial_shape[0], "initial_cols": initial_shape[1],
                "final_rows": final_shape[0], "final_cols": final_shape[1],
                "dropped_columns": columns_to_drop,
                "transformations_applied": transform_actions
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
            preview_data = df.head(10).fillna("").to_dict(orient='records')

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
