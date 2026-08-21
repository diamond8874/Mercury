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
    goal_lower = (goal or "").lower()
    for col in df.columns:
        col_lower = col.lower()
        
        # Check if user explicitly requested action for this column in goal
        user_wants_drop = col_lower in goal_lower and any(kw in goal_lower for kw in ["drop", "remove", "delete", "omit", "eliminate"])
        user_wants_keep = col_lower in goal_lower and any(kw in goal_lower for kw in ["keep", "retain", "include", "save"])

        if user_wants_drop:
            action = "drop"
            reason = f"Explicitly requested to drop column '{col}' based on user goal."
            trans = None
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

def apply_column_transformation(df, col, trans):
    """
    Executes advanced, versatile column transformations specified by AI or user prompts.
    Supports:
    - String cases & cleaning: upper, lower, title, strip, clean currency/symbols
    - Numeric conversions & imputations: mean, median, mode, zero, coerce numeric
    - Encoding: label encoding, category codes
    - Date/Time parsing & feature extraction: year, month, datetime formatting
    - Scaling & Math: min-max normalization, z-score standardization, log transform, rounding
    """
    if col not in df.columns:
        return df, f"Column '{col}' not found"

    trans_str = (trans or "").lower().strip()
    import re

    # 0. Value Replacement / Cell Mapping (e.g., "replace 'Tesla' with 'Tesla Motors'", "change 'NY' to 'New York'")
    replace_match = re.search(r"(?:replace|substitute|change|rename|map)\s+(?:value\s+)?['\"]?([^'\"]+?)['\"]?\s+(?:with|to|->)\s+['\"]?([^'\"]+?)['\"]?$", trans_str, re.IGNORECASE)
    if replace_match:
        old_val, new_val = replace_match.group(1).strip(), replace_match.group(2).strip()
        # Convert df column to string for consistent text value replacement
        df[col] = df[col].astype(str).replace(old_val, new_val)
        # Also try case-insensitive replace if string match
        df[col] = df[col].replace(to_replace=r'(?i)^' + re.escape(old_val) + r'$', value=new_val, regex=True)
        return df, f"Replaced cell values '{old_val}' with '{new_val}' in '{col}'"

    # Custom missing value fill (e.g., "fill missing with 'None'")
    if any(k in trans_str for k in ['fill missing', 'replace missing', 'impute missing']) and not any(k in trans_str for k in ['mean', 'median', 'mode']):
        fill_match = re.search(r"(?:with|to)\s+['\"]?([^'\"]+?)['\"]?$", trans_str, re.IGNORECASE)
        fill_val = fill_match.group(1).strip() if fill_match else "Unknown"
        df[col] = df[col].fillna(fill_val)
        return df, f"Filled missing values in '{col}' with '{fill_val}'"

    # Row Operations / Outlier / Duplicate Handling
    if any(k in trans_str for k in ['drop duplicate', 'remove duplicate', 'deduplicate']):
        df = df.drop_duplicates(subset=[col])
        return df, f"Removed duplicate rows based on column '{col}'"
    elif any(k in trans_str for k in ['drop na rows', 'remove missing rows', 'drop null rows', 'drop empty rows']):
        df = df.dropna(subset=[col])
        return df, f"Dropped rows with missing values in column '{col}'"
    elif any(k in trans_str for k in ['outlier', 'clip', 'trim outliers']):
        if pd.api.types.is_numeric_dtype(df[col]):
            q1, q3 = df[col].quantile(0.01), df[col].quantile(0.99)
            df[col] = df[col].clip(lower=q1, upper=q3)
            return df, f"Clipped 1st-99th percentile outliers in '{col}'"

    # 1. Date & Time Transformations
    if any(k in trans_str for k in ['date', 'datetime', 'time', 'timestamp']):
        if 'year' in trans_str:
            df[f"{col}_year"] = pd.to_datetime(df[col], errors='coerce').dt.year
            return df, f"Extracted year from '{col}' into '{col}_year'"
        elif 'month' in trans_str:
            df[f"{col}_month"] = pd.to_datetime(df[col], errors='coerce').dt.month
            return df, f"Extracted month from '{col}' into '{col}_month'"
        else:
            import datetime
            def _parse_val(v):
                if pd.isna(v) or v is None: return ""
                v_str = str(v).strip()
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                    try:
                        dt = datetime.datetime.strptime(v_str, fmt)
                        return dt.strftime("%Y-%m-%d %H:%M:%S")
                    except Exception: pass
                return v_str
            df[col] = df[col].apply(_parse_val)
            return df, f"Standardized datetime in '{col}'"

    # 2. String & Text Case Transformations
    elif any(k in trans_str for k in ['upper', 'uppercase']):
        df[col] = df[col].astype(str).str.upper()
        return df, f"Converted '{col}' to uppercase"
    elif any(k in trans_str for k in ['lower', 'lowercase']):
        df[col] = df[col].astype(str).str.lower()
        return df, f"Converted '{col}' to lowercase"
    elif any(k in trans_str for k in ['title', 'titlecase', 'capitalize']):
        df[col] = df[col].astype(str).str.title()
        return df, f"Capitalized '{col}'"
    elif any(k in trans_str for k in ['strip', 'trim', 'whitespace']):
        df[col] = df[col].astype(str).str.strip()
        return df, f"Cleaned whitespace in '{col}'"

    # 3. Currency / Symbol Cleaning
    elif any(k in trans_str for k in ['currency', 'symbol', 'price', '$', 'dollar', 'strip symbols']):
        df[col] = df[col].astype(str).str.replace(r'[\$,€,£,,\s]', '', regex=True)
        df[col] = pd.to_numeric(df[col], errors='coerce')
        return df, f"Cleaned currency symbols and converted '{col}' to numeric"

    # 4. Encoding
    elif any(k in trans_str for k in ['encode', 'label encode', 'category', 'factorize']):
        df[col] = df[col].astype('category').cat.codes
        return df, f"Label-encoded categorical column '{col}'"

    # 5. Imputation Strategies
    elif 'mean' in trans_str:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        df[col] = df[col].fillna(df[col].mean())
        return df, f"Imputed missing in '{col}' with column mean"
    elif 'median' in trans_str:
        df[col] = pd.to_numeric(df[col], errors='coerce')
        df[col] = df[col].fillna(df[col].median())
        return df, f"Imputed missing in '{col}' with column median"
    elif 'mode' in trans_str:
        mode_val = df[col].mode()[0] if not df[col].mode().empty else "Unknown"
        df[col] = df[col].fillna(mode_val)
        return df, f"Imputed missing in '{col}' with mode"
    elif any(k in trans_str for k in ['zero', 'fill 0', '0']):
        df[col] = df[col].fillna(0)
        return df, f"Filled missing in '{col}' with 0"

    # 6. Scaling, Normalization & Math
    elif any(k in trans_str for k in ['normalize', 'min-max', 'minmax', 'scale']):
        numeric_series = pd.to_numeric(df[col], errors='coerce')
        min_v, max_v = numeric_series.min(), numeric_series.max()
        if max_v != min_v:
            df[col] = (numeric_series - min_v) / (max_v - min_v)
        return df, f"Applied Min-Max scaling to '{col}'"
    elif any(k in trans_str for k in ['standardize', 'z-score', 'zscore']):
        numeric_series = pd.to_numeric(df[col], errors='coerce')
        std_v = numeric_series.std()
        if std_v != 0:
            df[col] = (numeric_series - numeric_series.mean()) / std_v
        return df, f"Standardized '{col}' with Z-score"
    elif 'log' in trans_str:
        import numpy as np
        df[col] = np.log1p(pd.to_numeric(df[col], errors='coerce').clip(lower=0))
        return df, f"Applied Log(1+x) transformation to '{col}'"
    elif any(k in trans_str for k in ['round', 'integer', 'int']):
        df[col] = pd.to_numeric(df[col], errors='coerce').round()
        return df, f"Rounded '{col}' to integers"

    # Default / Fallback numeric or string imputation
    elif pd.api.types.is_numeric_dtype(df[col]):
        df[col] = df[col].fillna(df[col].median())
        return df, f"Imputed missing in '{col}' with median"
    else:
        df[col] = df[col].fillna("Unknown")
        return df, f"Imputed missing in '{col}' with 'Unknown'"


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
                        df, msg = apply_column_transformation(df, col, trans)
                        transform_actions.append(msg)
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
