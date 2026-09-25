"""
services/dataset_service.py
---------------------------
Core dataset service handling file parsing, session creation, column updates,
dataset cleaning, and dry runs.
"""
import os
import uuid
import datetime
import logging
import pandas as pd
from flask import current_app

from utils.session_manager import save_session, load_session
from utils.upload_validator import validate_upload
from utils.helpers import read_csv_robust, safe_to_excel
from services.cleaning import run_cleaning_engine, build_cleaning_plan, validate_plan


def get_safe_preview(df, n=15):
    """Safely converts DataFrame head to dict records for JSON serialization."""
    if df is None or df.empty:
        return []
    df_slice = df.head(n).copy().astype(object)
    df_slice = df_slice.where(df_slice.notna(), "")
    return df_slice.to_dict(orient='records')


def save_uploaded_file(file_storage, user_id=None):
    """
    Saves and validates an uploaded file as <uuid>.<ext>, creates a new session,
    and returns (session_dict, None) or (None, (error_msg, status_code)).
    """
    from werkzeug.utils import secure_filename
    original_filename = secure_filename(file_storage.filename)
    unique_id = str(uuid.uuid4())
    file_ext = original_filename.rsplit('.', 1)[1].lower()
    saved_filename = f"{unique_id}.{file_ext}"
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], saved_filename)

    file_storage.save(file_path)
    logging.info("Upload saved: %s (original: %s)", saved_filename, original_filename)

    # Content validation
    valid, val_err = validate_upload(file_path, file_ext)
    if not valid:
        try:
            os.remove(file_path)
        except OSError:
            pass
        logging.warning("Upload rejected (%s): %s", saved_filename, val_err)
        return None, (val_err, 400)

    try:
        sheets = []
        if file_ext in ['xlsx', 'xls']:
            xls = pd.ExcelFile(file_path)
            sheets = xls.sheet_names
            df = pd.read_excel(file_path, sheet_name=sheets[0])
        else:
            df = read_csv_robust(file_path)
            sheets = ["Default"]

        num_rows, num_cols = df.shape
        columns = []

        for col in df.columns:
            sample_vals = df[col].dropna().head(3).tolist()
            sample_vals = [
                str(x) if isinstance(x, (pd.Timestamp, datetime.datetime, type(pd.NaT))) else x
                for x in sample_vals
            ]
            null_count = int(df[col].isnull().sum())

            columns.append({
                "name": col,
                "type": str(df[col].dtype),
                "null_count": null_count,
                "sample_values": sample_vals
            })

        preview_data = get_safe_preview(df, 15)

        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "owner_id": user_id,
            "name": original_filename,
            "original_filename": original_filename,
            "file_id": saved_filename,
            "file_type": file_ext,
            "sheets": sheets,
            "row_count": num_rows,
            "col_count": num_cols,
            "columns": columns,
            "preview": preview_data,
            "raw_preview": preview_data,
            "goal": "",
            "column_actions": {},
            "chat_history": [
                {
                    "role": "assistant",
                    "content": f"Hi! I've loaded your dataset: `{original_filename}`. What model do you plan to train, or what is your data analysis goal?"
                }
            ],
            "charts": [],
            "cleaned_filename": None,
            "created_at": datetime.datetime.now().isoformat(),
            "last_accessed": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        save_session(session_data)

        return {
            "session_id": session_id,
            "file_id": saved_filename,
            "original_name": original_filename,
            "file_type": file_ext,
            "sheets": sheets,
            "row_count": num_rows,
            "col_count": num_cols,
            "columns": columns,
            "preview": preview_data,
            "chat_history": session_data["chat_history"]
        }, None

    except Exception as e:
        logging.error(f"Error parsing uploaded file: {str(e)}")
        try:
            os.remove(file_path)
        except OSError:
            pass
        return None, (f"Failed to parse Excel/CSV file: {str(e)}", 500)


def process_cleaning_for_session(session_data, actions, sheet_name="Default"):
    """
    Executes cleaning actions on a session's dataset and saves the result to disk.
    Returns (result_dict, None) or (None, (error_msg, status_code)).
    """
    file_id = session_data.get("file_id")
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_id)
    if not os.path.exists(file_path):
        return None, ("Uploaded file not found", 404)

    try:
        file_ext = file_id.rsplit('.', 1)[1].lower()
        if file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name != "Default" else 0)
        else:
            df = read_csv_robust(file_path)

        session_data["column_actions"] = actions

        clean_res = run_cleaning_engine(df, actions)
        df = clean_res["df"]
        audit_log = clean_res["audit_log"]
        quality_metrics = clean_res["quality_metrics"]
        stats = clean_res["stats"]

        session_id = session_data["session_id"]
        output_filename = f"cleaned_{session_id}.xlsx"
        output_path = os.path.join(current_app.config['OUTPUT_FOLDER'], output_filename)
        safe_to_excel(df, output_path, index=False)
        logging.info("Cleaned dataset saved to %s", output_path)

        session_data["cleaned_filename"] = output_filename
        session_data["audit_log"] = audit_log
        session_data["quality_metrics"] = quality_metrics
        session_data["stats"] = stats
        session_data["row_count"] = df.shape[0]
        session_data["col_count"] = df.shape[1]
        session_data["charts"] = []

        preview_data = get_safe_preview(df, 15)
        session_data["preview"] = preview_data
        session_data["bg_result"] = {
            "preview": preview_data,
            "stats": stats,
            "charts": [],
            "quality_metrics": quality_metrics,
            "download_url": f"/api/download/{output_filename}"
        }
        confirm_msg = (
            f"Excellent! I've clean-processed the dataset using the unified cleaning engine. "
            f"It has {df.shape[0]} rows and {df.shape[1]} columns. You can download the clean file or view diagnostics in the report."
        )
        session_data["chat_history"].append({"role": "assistant", "content": confirm_msg})
        save_session(session_data)

        return {
            "success": True,
            "download_url": f"/api/download/{output_filename}",
            "stats": stats,
            "quality_metrics": quality_metrics,
            "audit_log": audit_log,
            "charts": [],
            "preview": preview_data,
            "chat_history": session_data["chat_history"]
        }, None

    except Exception as e:
        logging.error("Error processing dataset: %s", str(e))
        return None, (f"Failed to clean and process dataset: {str(e)}", 500)


def update_cell_value(session_data, row_idx, col_name, new_val):
    """
    Updates a single cell in the session file.
    Returns (result_dict, None) or (None, (error_msg, status_code)).
    """
    file_id = session_data.get("file_id")
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_id)
    if not os.path.exists(file_path):
        return None, ("File not found", 404)

    try:
        sheet_name = session_data.get("sheet_name", 0)
        file_ext = file_id.rsplit('.', 1)[1].lower()
        if file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name not in ("Default", None) else 0)
        else:
            df = read_csv_robust(file_path)

        row_i = int(row_idx)
        if col_name not in df.columns or not (0 <= row_i < len(df)):
            return None, ("Invalid row index or column name", 400)

        target_dtype = df[col_name].dtype
        casted_val = new_val
        if new_val is not None and str(new_val).strip() != "":
            try:
                if pd.api.types.is_integer_dtype(target_dtype):
                    casted_val = int(float(new_val))
                elif pd.api.types.is_float_dtype(target_dtype):
                    casted_val = float(new_val)
                elif pd.api.types.is_bool_dtype(target_dtype):
                    casted_val = str(new_val).strip().lower() in ('true', '1', 'yes', 'y')
                elif pd.api.types.is_datetime64_any_dtype(target_dtype):
                    casted_val = pd.to_datetime(new_val)
            except Exception:
                casted_val = new_val

        df.at[row_i, col_name] = casted_val

        working_filename = f"edited_{file_id.split('.')[0]}.xlsx"
        working_path = os.path.join(current_app.config['OUTPUT_FOLDER'], working_filename)
        safe_to_excel(df, working_path, index=False)
        session_data["cleaned_filename"] = working_filename
        session_data["preview"] = get_safe_preview(df, 15)
        save_session(session_data)

        return {
            "success": True,
            "message": f"Updated cell at row {row_i}, column '{col_name}' to '{casted_val}'"
        }, None

    except Exception as e:
        return None, (f"Failed to update cell: {str(e)}", 500)


def dry_run_plan(session_data, actions, sheet_name="Default"):
    """
    Builds and validates a cleaning plan without modifying the dataset on disk.
    Returns (result_dict, None) or (None, (error_msg, status_code)).
    """
    file_id = session_data.get("file_id")
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_id)
    if not os.path.exists(file_path):
        return None, ("Uploaded file not found", 404)

    try:
        file_ext = file_id.rsplit('.', 1)[1].lower()
        if file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name != "Default" else 0)
        else:
            df = read_csv_robust(file_path)

        full_plan = []
        for col, col_data in actions.items():
            action = col_data.get('action')
            trans = col_data.get('transformation')
            if action == 'transform' and trans:
                col_plan = build_cleaning_plan(col, trans, df)
                full_plan.extend(col_plan)
            elif action == 'drop':
                full_plan.append({
                    "column": col,
                    "operation": "drop_column",
                    "parameters": {},
                    "order": len(full_plan) + 1,
                    "raw_step": f"drop {col}",
                    "message": f"Drop column '{col}'."
                })

        val_results = validate_plan(full_plan, df)
        return {
            "success": True,
            "cleaning_plan": full_plan,
            "validation": val_results
        }, None

    except Exception as e:
        return None, (f"Dry run failed: {str(e)}", 500)
