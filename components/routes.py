import os
import uuid
import json
import logging
import datetime
import threading
import re
from flask import Blueprint, request, jsonify, send_from_directory, current_app, Response, stream_with_context
from werkzeug.utils import secure_filename
import pandas as pd

def get_safe_preview(df, n=10):
    """Safely converts DataFrame head to dict records for JSON serialization."""
    if df is None or df.empty:
        return []
    df_slice = df.head(n).copy().astype(object)
    df_slice = df_slice.where(df_slice.notna(), "")
    return df_slice.to_dict(orient='records')


# Services
from services.ai_service import get_llm_client
from services.data_service import (
    summarize_schema,
    generate_mock_recommendations,
    run_background_process,
    apply_column_transformation,
    polish_and_standardize_prompt,
    match_column_name
)

# Utils
from utils.helpers import allowed_file, parse_json_response
from utils.session_manager import load_session, save_session, invalidate_session_cache
from utils.job_tracker import _set_job_state, _get_job_state, _update_job_progress

# Matplotlib & PDF generation imports
import matplotlib
matplotlib.use('Agg')  # Set non-interactive backend for server safety
import matplotlib.pyplot as plt

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    reportlab_installed = True
except ImportError:
    reportlab_installed = False

# Initialize blueprint
api_blueprint = Blueprint('api', __name__)

@api_blueprint.route('/')
def index():
    return send_from_directory('static', 'index.html')

@api_blueprint.route('/favicon.ico')
def favicon():
    return '', 204

# Session REST Management Endpoints
@api_blueprint.route('/api/sessions', methods=['GET'])
def list_sessions():
    sessions = []
    session_folder = current_app.config['SESSION_FOLDER']
    for name in os.listdir(session_folder):
        if name.endswith('.json'):
            path = os.path.join(session_folder, name)
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    sessions.append({
                        "session_id": data.get("session_id"),
                        "name": data.get("name"),
                        "original_filename": data.get("original_filename"),
                        "goal": data.get("goal"),
                        "created_at": data.get("created_at")
                    })
            except Exception:
                pass
    sessions.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return jsonify(sessions)

@api_blueprint.route('/api/sessions/<session_id>', methods=['GET'])
def get_session_detail(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
    return jsonify(session_data)

@api_blueprint.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    try:
        if session_data.get("file_id"):
            upload_path = os.path.join(current_app.config['UPLOAD_FOLDER'], session_data["file_id"])
            if os.path.exists(upload_path):
                os.remove(upload_path)
        if session_data.get("cleaned_filename"):
            output_path = os.path.join(current_app.config['OUTPUT_FOLDER'], session_data["cleaned_filename"])
            if os.path.exists(output_path):
                os.remove(output_path)
    except Exception as ex:
        logging.warning(f"Error removing files during session delete: {str(ex)}")

    session_folder = current_app.config['SESSION_FOLDER']
    path = os.path.join(session_folder, f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
    invalidate_session_cache(session_id)
    return jsonify({"success": True})

# Refactored Core routes
@api_blueprint.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        unique_id = str(uuid.uuid4())
        file_ext = original_filename.rsplit('.', 1)[1].lower()
        saved_filename = f"{unique_id}.{file_ext}"
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], saved_filename)

        file.save(file_path)
        logging.info(f"File saved successfully to {file_path}")

        try:
            sheets = []
            if file_ext in ['xlsx', 'xls']:
                xls = pd.ExcelFile(file_path)
                sheets = xls.sheet_names
                df = pd.read_excel(file_path, sheet_name=sheets[0])
            else:
                df = pd.read_csv(file_path)
                sheets = ["Default"]

            num_rows, num_cols = df.shape
            columns = []

            for col in df.columns:
                sample_vals = df[col].dropna().head(3).tolist()
                sample_vals = [str(x) if isinstance(x, (pd.Timestamp, datetime.datetime, type(pd.NaT))) else x for x in sample_vals]
                null_count = int(df[col].isnull().sum())

                columns.append({
                    "name": col,
                    "type": str(df[col].dtype),
                    "null_count": null_count,
                    "sample_values": sample_vals
                })

            preview_data = get_safe_preview(df, 5)

            # Create fresh session record
            session_id = str(uuid.uuid4())
            session_data = {
                "session_id": session_id,
                "name": original_filename,
                "original_filename": original_filename,
                "file_id": saved_filename,
                "file_type": file_ext,
                "sheets": sheets,
                "row_count": num_rows,
                "col_count": num_cols,
                "columns": columns,
                "preview": preview_data,
                "goal": "",
                "column_actions": {},
                "chat_history": [
                    {"role": "assistant", "content": f"Hi! I've loaded your dataset: `{original_filename}`. What model do you plan to train, or what is your data analysis goal?"}
                ],
                "charts": [],
                "cleaned_filename": None,
                "created_at": datetime.datetime.now().isoformat()
            }
            save_session(session_data)

            return jsonify({
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
            })

        except Exception as e:
            logging.error(f"Error parsing uploaded file: {str(e)}")
            return jsonify({"error": f"Failed to parse Excel/CSV file: {str(e)}"}), 500

    return jsonify({"error": "Unsupported file format. Please upload Excel (.xlsx, .xls) or CSV."}), 400

@api_blueprint.route('/api/analyze', methods=['POST'])
def analyze_schema():
    data = request.json or {}
    session_id = data.get("session_id")
    goal = data.get("goal")
    api_key = data.get("api_key")
    sheet_name = data.get("sheet_name", "Default")

    if not session_id or not goal:
        return jsonify({"error": "Missing session_id or goal in request"}), 400

    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    session_data["goal"] = goal
    session_data["status"] = "queued"
    session_data["progress"] = 5
    save_session(session_data)
    _set_job_state(session_id, "analyzing", progress=5, progress_msg="Queued for analysis")

    provider = data.get("provider") or os.environ.get("LLM_PROVIDER")
    model = data.get("model") or os.environ.get("LLM_MODEL") or "nvidia/llama-3.1-nemotron-70b-instruct"
    base_url = data.get("base_url")
    is_mock = (api_key == "MOCK")
    
    # Start background task
    thread = threading.Thread(
        target=background_analyze,
        args=(session_id, goal, api_key, sheet_name, provider, model, base_url, is_mock, current_app._get_current_object())
    )
    thread.daemon = True
    thread.start()

    return jsonify({
        "status": "queued",
        "session_id": session_id,
        "message": "Analysis started in background"
    })

def background_analyze(session_id, goal, api_key, sheet_name, provider, model, base_url, is_mock, app_context):
    with app_context.app_context():
        try:
            session_data = load_session(session_id)
            if not session_data:
                return

            session_data["status"] = "analyzing"
            session_data["progress"] = 15
            save_session(session_data)
            _update_job_progress(session_id, 15, "Loading file from disk...")

            file_id = session_data["file_id"]
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_id)

            if not os.path.exists(file_path):
                raise Exception("Uploaded file not found on disk")

            client = None if is_mock else get_llm_client(api_key=api_key, provider=provider, model=model, base_url=base_url)

            if not is_mock and not client:
                raise Exception("API Key is required. Please set it in the settings panel.")

            session_data["progress"] = 25
            save_session(session_data)
            _update_job_progress(session_id, 25, "Parsing dataset...")

            # Load file
            file_ext = file_id.rsplit('.', 1)[1].lower()
            if file_ext in ['xlsx', 'xls']:
                df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name != "Default" else 0)
            else:
                df = pd.read_csv(file_path)

            session_data["progress"] = 40
            save_session(session_data)
            _update_job_progress(session_id, 40, "Generating recommendations...")

            if is_mock:
                recommendations = generate_mock_recommendations(df, goal)
                col_actions = {r["column"]: {"action": r["action"], "reason": r["reason"], "transformation": r["transformation"]} for r in recommendations}
                session_data["column_actions"] = col_actions

                intro_msg = f"Goal set: **{goal}**.<br>Using mock offline recommendations. I suggest dropping redundant columns. You can edit the suggestions in the grid."
                session_data["chat_history"].append({"role": "user", "content": f"My data cleaning goal is: {goal}"})
                session_data["chat_history"].append({"role": "assistant", "content": intro_msg})
                session_data["recommendations"] = recommendations
                
                session_data["status"] = "analyze_done"
                session_data["result"] = {"recommendations": recommendations}
                session_data["progress"] = 100
                save_session(session_data)
                _set_job_state(session_id, "analyze_done", result={"recommendations": recommendations}, progress=100, progress_msg="Done")
                return

            # Prepare real request
            schema_summary = summarize_schema(df, max_samples=1)
            prompt = f"""
You are a brilliant Data Scientist and AI cleaning agent.
The user wants to prepare a dataset for the following specific Goal:
"{goal}"

Here is the dataset schema summary:
{json.dumps(schema_summary, indent=2)}

Analyze each column and recommend whether to KEEP, DROP, or TRANSFORM it.
CRITICAL RULES FOR RECOMMENDATIONS:
1. Default EVERY column to "action": "keep" unless the user's Goal explicitly named that specific column to be dropped (e.g. "drop Customer_ID").
2. DO NOT set "action": "drop" on any column unless the user specifically named that column to be dropped.
3. Phrases like "remove duplicates", "remove nulls", "remove rows", or "clean dataset" refer to row/cell operations — DO NOT set "action": "drop" on any column for these general phrases!
4. If the user's Goal mentions value replacements or transformations for a column (e.g. "CardiovascularDisease tranform 0-> no and 1->yes"), set "action": "transform" and put the transformation instruction in "transformation".
5. Provide a clear, concise, educational reason for each recommendation.


Return valid JSON only in this exact structure:
{{
  "recommendations": [
    {{
      "column": "column_name",
      "action": "keep" | "drop" | "transform",
      "reason": "Brief, human-readable reason why this action is recommended.",
      "transformation": "Description of suggested transformation or null if action is keep or drop"
    }}
  ]
}}
"""
            session_data["progress"] = 60
            save_session(session_data)
            _update_job_progress(session_id, 60, "Consulting AI model...")

            logging.info(f"Requesting column recommendations from model {model}...")
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    top_p=1,
                    max_tokens=1024,
                    seed=42
                )
                response_text = completion.choices[0].message.content
                ai_data = parse_json_response(response_text)

                recommendations = ai_data.get("recommendations", [])
                col_actions = {r["column"]: {"action": r["action"], "reason": r["reason"], "transformation": r["transformation"]} for r in recommendations}
                session_data["column_actions"] = col_actions

                dropped_list = [r["column"] for r in recommendations if r["action"] == 'drop']
                intro_msg = f"Goal set: **{goal}**.<br>I have completed scanning the dataset. I recommend dropping {len(dropped_list)} irrelevant features (like {', '.join(dropped_list[:2])}...) to prepare for your modeling objective. Let me know if you want to make overrides."

                session_data["chat_history"].append({"role": "user", "content": f"My data cleaning goal is: {goal}"})
                session_data["chat_history"].append({"role": "assistant", "content": intro_msg})
                session_data["recommendations"] = recommendations

                session_data["status"] = "analyze_done"
                session_data["result"] = {"recommendations": recommendations}
                session_data["progress"] = 100
                save_session(session_data)
                _set_job_state(session_id, "analyze_done", result={"recommendations": recommendations}, progress=100, progress_msg="Done")

            except Exception as api_err:
                logging.error(f"API call failed for model {model}, falling back to mock: {str(api_err)}")
                recommendations = generate_mock_recommendations(df, goal)
                col_actions = {r["column"]: {"action": r["action"], "reason": r["reason"], "transformation": r["transformation"]} for r in recommendations}
                session_data["column_actions"] = col_actions

                err_str = str(api_err)
                if "401" in err_str or "Authentication" in err_str:
                    reason_txt = "Invalid/Expired API Key (401)"
                elif "404" in err_str or "410" in err_str or "Not Found" in err_str or "Gone" in err_str:
                    reason_txt = "Model Endpoint Deprecated or Account Out of Credits (404/410)"
                elif "Timeout" in err_str:
                    reason_txt = "API Response Timeout"
                else:
                    reason_txt = err_str[:80]

                fallback_msg = f"Goal set: **{goal}**.<br>⚠️ API notice ({reason_txt}). Using offline recommendations fallback."
                session_data["chat_history"].append({"role": "user", "content": f"My data cleaning goal is: {goal}"})
                session_data["chat_history"].append({"role": "assistant", "content": fallback_msg})
                session_data["recommendations"] = recommendations
                
                session_data["status"] = "analyze_done"
                session_data["result"] = {"warning": str(api_err), "recommendations": recommendations}
                session_data["progress"] = 100
                session_data["warning"] = f"AI API is currently experiencing issues ({str(api_err)}). Falling back to local offline recommendations."
                save_session(session_data)
                _set_job_state(session_id, "analyze_done", result={"warning": str(api_err), "recommendations": recommendations}, progress=100, progress_msg="Done")

        except Exception as e:
            logging.error(f"Error during AI analysis background task: {str(e)}")
            session_data["status"] = "error"
            session_data["error"] = str(e)
            save_session(session_data)
            _set_job_state(session_id, "error", error=str(e))

@api_blueprint.route('/api/process', methods=['POST'])
def process_dataset():
    data = request.json or {}
    session_id = data.get("session_id")
    actions = data.get("actions")
    api_key = data.get("api_key")
    sheet_name = data.get("sheet_name", "Default")

    if not session_id or not actions:
        return jsonify({"error": "Missing session_id or actions in request"}), 400

    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    file_id = session_data["file_id"]
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_id)
    if not os.path.exists(file_path):
        return jsonify({"error": "Uploaded file not found"}), 404

    try:
        # Load file
        file_ext = file_id.rsplit('.', 1)[1].lower()
        if file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name != "Default" else 0)
        else:
            df = pd.read_csv(file_path)

        initial_shape = df.shape
        df.columns = df.columns.str.strip()

        initial_nulls = df.isnull().sum().to_dict()
        initial_duplicates = int(df.duplicated().sum())

        columns_to_drop = []
        columns_to_keep = []
        transform_actions = []

        session_data["column_actions"] = actions  # Save approved action choices

        for col, col_data in actions.items():
            action = col_data.get('action')
            trans = col_data.get('transformation')

            if col not in df.columns:
                # Check for case-insensitive match
                matched = [c for c in df.columns if c.lower() == str(col).lower()]
                if matched:
                    col = matched[0]
                else:
                    continue

            if action == 'drop':
                columns_to_drop.append(col)
            elif action == 'transform':
                columns_to_keep.append(col)
                try:
                    df, msg = apply_column_transformation(df, col, trans)
                    transform_actions.append(msg)
                except Exception as ex:
                    logging.warning(f"Failed to transform column {col}: {str(ex)}")
                    transform_actions.append(f"Failed to transform '{col}': {str(ex)}")
            else:
                columns_to_keep.append(col)
                # Explicit keep: do not modify column data or silently impute

        if columns_to_drop:
            df = df.drop(columns=columns_to_drop)

        final_shape = df.shape
        final_nulls = df.isnull().sum().to_dict()
        final_duplicates = int(df.duplicated().sum())

        # Save to output Excel
        output_filename = f"cleaned_{file_id.split('.')[0]}.xlsx"
        output_path = os.path.join(current_app.config['OUTPUT_FOLDER'], output_filename)
        df.to_excel(output_path, index=False)
        logging.info(f"Cleaned dataset saved to {output_path}")

        session_data["cleaned_filename"] = output_filename

        stats = {
            "initial_rows": initial_shape[0],
            "initial_cols": initial_shape[1],
            "final_rows": final_shape[0],
            "final_cols": final_shape[1],
            "dropped_columns": columns_to_drop,
            "transformations_applied": transform_actions,
            "null_before": sum(initial_nulls.values()),
            "null_after": sum(final_nulls.values()),
            "duplicate_before": initial_duplicates,
            "duplicate_after": final_duplicates
        }


        # Visualizations are rendered on demand via the custom_chart route
        session_data["charts"] = []
        rendered_charts = []
        preview_data = get_safe_preview(df, 10)

        # Append chat confirmation
        confirm_msg = f"Excellent! I've clean-processed the dataset. It has been reduced from **{initial_shape[1]}** features to **{final_shape[1]}** signals. You can download the clean file or view the charts on the right dashboard tabs."
        session_data["chat_history"].append({"role": "assistant", "content": confirm_msg})
        save_session(session_data)

        return jsonify({
            "success": True,
            "download_url": f"/api/download/{output_filename}",
            "stats": stats,
            "charts": rendered_charts,
            "preview": preview_data,
            "chat_history": session_data["chat_history"]
        })

    except Exception as e:
        logging.error(f"Error processing dataset: {str(e)}")
        return jsonify({"error": f"Failed to clean and process dataset: {str(e)}"}), 500

# Trigger background processing (called by frontend after analyze or chat schema change)
@api_blueprint.route('/api/sessions/<session_id>/trigger_process', methods=['POST'])
def trigger_background_process(session_id):
    data = request.json or {}
    api_key = data.get("api_key")

    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    # Store sheet_name in session for the background worker
    sheet_name = data.get("sheet_name", "Default")
    session_data["sheet_name"] = sheet_name

    # Save manual grid actions if provided
    if "column_actions" in data:
        session_data["column_actions"] = data["column_actions"]
    elif "actions" in data:
        session_data["column_actions"] = data["actions"]

    save_session(session_data)

    # Mark as queued and fire thread
    _set_job_state(session_id, "processing")
    t = threading.Thread(
        target=run_background_process,
        args=(current_app._get_current_object(), session_id, api_key),
        daemon=True
    )
    t.start()

    return jsonify({"status": "processing", "message": "Background processing started."})

@api_blueprint.route('/api/sessions/<session_id>/status', methods=['GET'])
def get_processing_status(session_id):
    job = _get_job_state(session_id)
    session_data = load_session(session_id)

    if not session_data and job.get("status") in ["idle", None]:
        return jsonify({"error": "Session not found"}), 404

    # If job memory state is idle/none, fall back to session JSON state
    if job.get("status") in ["idle", None] and session_data:
        status = session_data.get("status", "unknown")
        progress = session_data.get("progress", 0)
        res = session_data.get("bg_result") or session_data.get("result", {})
        
        if status in ["done", "analyze_done"] or session_data.get("cleaned_filename"):
            if session_data.get("cleaned_filename") and not res.get("download_url"):
                res["download_url"] = f"/api/download/{session_data['cleaned_filename']}"
            return jsonify({
                "status": "done",
                "result": res,
                "progress": 100,
                "progress_msg": "Done!"
            })
        elif status == "error":
            return jsonify({
                "status": "error",
                "error": session_data.get("error", "Unknown error"),
                "progress": progress
            })
        elif status:
            return jsonify({
                "status": status,
                "progress": progress,
                "result": res
            })

    return jsonify(job)

# Conversational Chat Route (non-streaming fallback, kept for compatibility)
@api_blueprint.route('/api/sessions/<session_id>/chat', methods=['POST'])
def chat_session(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    data = request.json or {}
    message = data.get("message")
    api_key = data.get("api_key")

    if not message:
        return jsonify({"error": "Missing message in request"}), 400

    # Append user message FIRST so it persists even on error
    session_data["chat_history"].append({"role": "user", "content": message})

    provider = data.get("provider") or os.environ.get("LLM_PROVIDER")
    model = data.get("model") or os.environ.get("LLM_MODEL")
    base_url = data.get("base_url")
    if not model:
        return jsonify({"error": "No model specified and LLM_MODEL not set in environment"}), 400

    is_mock = (api_key == "MOCK")
    client = None if is_mock else get_llm_client(api_key=api_key, provider=provider, model=model, base_url=base_url)

    def run_local_fallback(msg_lower, current_session):
        schema_updates = {}
        columns = [col["name"] for col in current_session["columns"]]
        clean_msg = re.sub(
            r'\b(remove|drop|delete)\s+(duplicates?|nulls?|nans?|missing|rows?|placeholders?|outliers?|invalid|bad)\b',
            '',
            msg_lower,
            flags=re.IGNORECASE
        )
        for col in columns:
            col_lower = col.lower()
            col_spaced = col_lower.replace('_', ' ')
            col_pattern = rf"\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b"
            if re.search(col_pattern, clean_msg):
                drop_pattern = rf"\b(?:drop|remove|delete|eliminate)\b.*\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b|\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b.*\b(?:drop|remove|delete|eliminate)\b"
                if re.search(drop_pattern, clean_msg):
                    schema_updates[col] = {"action": "drop", "reason": "Dropped by user request in chat.", "transformation": None}
                elif any(kw in msg_lower for kw in ["keep", "add", "retain", "include"]):
                    schema_updates[col] = {"action": "keep", "reason": "Kept by user request in chat.", "transformation": None}
                elif any(kw in msg_lower for kw in ["transform", "convert", "encode", "impute"]):
                    schema_updates[col] = {"action": "transform", "reason": "Transform requested in chat.", "transformation": "Custom transform"}
        return schema_updates


    if is_mock or not client:
        msg_lower = message.lower()
        schema_updates = run_local_fallback(msg_lower, session_data)

        if schema_updates:
            response_msg = f"Done! I've updated the action for **{', '.join(schema_updates.keys())}**. The schema grid on the right has been refreshed."
            for col, act in schema_updates.items():
                session_data["column_actions"][col] = act
        else:
            response_msg = f"I'm here to help with your goal: **{session_data['goal']}**. You can ask me to keep, drop, or transform any specific column by name."

        session_data["chat_history"].append({"role": "assistant", "content": response_msg})
        save_session(session_data)
        return jsonify({
            "message": response_msg,
            "schema_updates": schema_updates,
            "column_actions": session_data["column_actions"],
            "chat_history": session_data["chat_history"]
        })

    try:
        schema_context = []
        for col in session_data["columns"]:
            name = col["name"]
            action_data = session_data["column_actions"].get(name, {"action": "keep", "reason": "Default", "transformation": ""})
            schema_context.append({
                "column": name,
                "type": col["type"],
                "null_count": col["null_count"],
                "sample_values": col["sample_values"],
                "current_action": action_data["action"],
                "reason": action_data.get("reason", ""),
                "transformation": action_data.get("transformation")
            })

        # Build conversation messages for the model (proper multi-turn format)
        messages_for_model = []
        for turn in session_data["chat_history"][:-1]:  # exclude the just-appended user message
            messages_for_model.append({"role": turn["role"], "content": turn["content"]})

        system_prompt = f"""You are an expert Data Scientist and AI cleaning assistant.
The goal is: "{session_data['goal']}"

Current columns and chosen actions:
{json.dumps(schema_context, indent=2)}

When the user asks for a schema change, answer with valid JSON only in this format:
{{
  "message": "Your human-friendly response.",
  "schema_updates": {{
    "ExactColumnName": {{
      "action": "keep" | "drop" | "transform",
      "reason": "Reason for the change.",
      "transformation": "Description or null"
    }}
  }}
}}
If no changes are needed, return empty schema_updates {{}}.
"""

        messages_for_model.append({"role": "user", "content": f"{system_prompt}\n\nUser message: {message}"})

        logging.info(f"Sending chat query to model {model}...")
        completion = client.chat.completions.create(
            model=model,
            messages=messages_for_model,
            temperature=0.2,
            top_p=1,
            max_tokens=1024,
            seed=42
        )
        response_text = completion.choices[0].message.content

        try:
            ai_data = parse_json_response(response_text)
            response_msg = ai_data.get("message", "I have processed your request.")
            schema_updates = ai_data.get("schema_updates", {})
        except Exception:
            # Model returned plain text instead of JSON – still use it
            response_msg = response_text.strip()
            schema_updates = {}

        # Apply schema updates and save
        for col, col_data in schema_updates.items():
            # Case-insensitive match for safety
            matched_col = next((c for c in session_data["column_actions"] if c.lower() == col.lower()), col)
            session_data["column_actions"][matched_col] = col_data

        session_data["chat_history"].append({"role": "assistant", "content": response_msg})
        save_session(session_data)

        return jsonify({
            "message": response_msg,
            "schema_updates": schema_updates,
            "column_actions": session_data["column_actions"],
            "chat_history": session_data["chat_history"]
        })

    except Exception as e:
        logging.error(f"Chat API failed: {str(e)}")
        # Fallback to local parser
        msg_lower = message.lower()
        schema_updates = run_local_fallback(msg_lower, session_data)
        response_msg = f"⚠️ AI API unavailable. Applied local parsing."
        if schema_updates:
            response_msg += f" Updated: **{', '.join(schema_updates.keys())}**."
            for col, act in schema_updates.items():
                session_data["column_actions"][col] = act
        else:
            response_msg += " No column changes detected. Try mentioning a column name with 'drop', 'keep', or 'transform'."

        session_data["chat_history"].append({"role": "assistant", "content": response_msg})
        save_session(session_data)
        return jsonify({
            "message": response_msg,
            "schema_updates": schema_updates,
            "column_actions": session_data["column_actions"],
            "chat_history": session_data["chat_history"]
        })

# Streaming Chat Route via Server-Sent Events
@api_blueprint.route('/api/sessions/<session_id>/chat/stream', methods=['POST'])
def chat_session_stream(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    data = request.json or {}
    message = data.get("message", "")
    api_key = data.get("api_key")

    if not message:
        return jsonify({"error": "Missing message"}), 400

    # Save user message immediately so it persists
    session_data["chat_history"].append({"role": "user", "content": message})
    save_session(session_data)

    provider = data.get("provider") or os.environ.get("LLM_PROVIDER")
    model = data.get("model") or os.environ.get("LLM_MODEL")
    base_url = data.get("base_url")

    is_mock = (api_key == "MOCK")
    client = None if is_mock else get_llm_client(api_key=api_key, provider=provider, model=model, base_url=base_url)

    def run_local_fallback_stream():
        """Local rule-based fallback that emits SSE events."""
        msg_lower = message.lower()
        schema_updates = {}
        columns = [col["name"] for col in session_data["columns"]]
        clean_msg = re.sub(
            r'\b(remove|drop|delete)\s+(duplicates?|nulls?|nans?|missing|rows?|placeholders?|outliers?|invalid|bad)\b',
            '',
            msg_lower,
            flags=re.IGNORECASE
        )
        for col in columns:
            col_lower = col.lower()
            col_spaced = col_lower.replace('_', ' ')
            col_pattern = rf"\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b"
            if re.search(col_pattern, clean_msg):
                drop_pattern = rf"\b(?:drop|remove|delete|eliminate)\b.*\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b|\b(?:{re.escape(col_lower)}|{re.escape(col_spaced)})\b.*\b(?:drop|remove|delete|eliminate)\b"
                if re.search(drop_pattern, clean_msg):
                    schema_updates[col] = {"action": "drop", "reason": "Dropped by user request in chat.", "transformation": None}
                elif any(kw in msg_lower for kw in ["keep", "add", "retain", "include"]):
                    schema_updates[col] = {"action": "keep", "reason": "Kept by user request in chat.", "transformation": None}
                elif any(kw in msg_lower for kw in ["transform", "convert", "encode", "impute"]):
                    schema_updates[col] = {"action": "transform", "reason": "Transform requested in chat.", "transformation": "Custom transform"}


        if schema_updates:
            response_msg = f"Done! I've updated the action for **{', '.join(schema_updates.keys())}**. The schema grid has been refreshed."
            for col, act in schema_updates.items():
                session_data["column_actions"][col] = act
        else:
            response_msg = f"I'm here to help with your goal: **{session_data['goal']}**. Mention a column name with 'drop', 'keep', or 'transform' to make changes."

        # Emit schema_updates event first
        trigger = len(schema_updates) > 0
        yield f"event: schema_updates\ndata: {json.dumps({'schema_updates': schema_updates, 'column_actions': session_data['column_actions'], 'trigger_reprocess': trigger})}\n\n"

        # Stream the response word by word
        for word in response_msg.split(' '):
            yield f"data: {json.dumps({'token': word + ' '})}\n\n"

        # Final done event
        session_data["chat_history"].append({"role": "assistant", "content": response_msg})
        save_session(session_data)

        # Auto-trigger background re-process if schema changed
        if trigger:
            t = threading.Thread(
                target=run_background_process,
                args=(current_app._get_current_object(), session_id, api_key),
                daemon=True
            )
            t.start()

        yield f"event: done\ndata: {json.dumps({'full_message': response_msg})}\n\n"

    def run_ai_stream():
        """Stream from Nvidia GLM-5.2 via SSE, extract schema_updates from full response."""
        schema_context = []
        for col in session_data["columns"]:
            name = col["name"]
            action_data = session_data["column_actions"].get(name, {"action": "keep", "reason": "Default", "transformation": ""})
            schema_context.append({
                "column": name,
                "type": col["type"],
                "null_count": col["null_count"],
                "sample_values": col["sample_values"],
                "current_action": action_data["action"],
                "reason": action_data.get("reason", ""),
                "transformation": action_data.get("transformation")
            })

        system_prompt = f"""You are an expert Data Scientist and AI cleaning assistant.
The goal is: "{session_data['goal']}"

Current columns and chosen actions:
{json.dumps(schema_context, indent=2)}

CRITICAL INSTRUCTIONS:
1. DO NOT set "action": "drop" on any column unless the user explicitly named that exact column by name to be dropped (e.g. "drop Year").
2. General phrases like "remove duplicates", "remove nulls", "remove rows" refer to dataset row operations — DO NOT set "action": "drop" on any column for these phrases.
3. If the user asks for schema updates, column actions, or cell value changes (e.g. "replace 'Tesla' with 'Tesla Motors'", "drop date column"), you MUST include the <<<SCHEMA_UPDATES>>> JSON block at the end of your response.
4. Format:
I have updated the dataset actions for your request.
<<<SCHEMA_UPDATES>>>
{{"column_name": {{"action": "drop|keep|transform", "reason": "...", "transformation": "replace 'OLD' with 'NEW' or 'uppercase' or 'label encode' or null"}}}}
<<<END>>>

5. ONLY include entries in <<<SCHEMA_UPDATES>>> for columns explicitly requested or modified by the user. Do NOT include unchanged columns.
6. Do NOT output internal monologue or thinking steps to the user. Respond concisely and cleanly.
"""

        # Build proper multi-turn messages
        messages_for_model = [{"role": "system", "content": system_prompt}]
        # Add prior conversation turns (skip last user msg, we'll add it below)
        for turn in session_data["chat_history"][:-1]:
            messages_for_model.append({"role": turn["role"], "content": turn["content"]})
        messages_for_model.append({"role": "user", "content": message})

        full_response = ""
        schema_updates = {}

        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages_for_model,
                temperature=0.3,
                top_p=1,
                max_tokens=1024,
                stream=True
            )

            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                if not chunk.choices or not getattr(chunk.choices[0], "delta", None):
                    continue
                delta = chunk.choices[0].delta
                token = getattr(delta, "content", None)
                if token is None:
                    continue

                full_response += token

                # Don't stream thinking process text or SCHEMA_UPDATES block to the user
                if "Here's a thinking process:" not in full_response and "<<<SCHEMA_UPDATES>>>" not in full_response:
                    yield f"data: {json.dumps({'token': token})}\n\n"

            # Extract schema updates from the full response
            if "Here's a thinking process:" in full_response:
                # Remove CoT thinking monologue from user-facing text
                if "<<<SCHEMA_UPDATES>>>" in full_response:
                    parts = full_response.split("<<<SCHEMA_UPDATES>>>")
                    visible_text = parts[0].split("Here's a thinking process:")[0].strip()
                    if not visible_text:
                        visible_text = "I have updated the dataset actions for your request."
                    json_block = parts[1].split("<<<END>>>")[0].strip() if "<<<END>>>" in parts[1] else ""
                    if json_block.startswith("```"):
                        json_block = re.sub(r"^```[a-z]*", "", json_block).rstrip("`").strip()
                    try:
                        schema_updates = json.loads(json_block)
                        for col, col_data in schema_updates.items():
                            matched_col = next((c for c in session_data["column_actions"] if c.lower() == col.lower()), col)
                            session_data["column_actions"][matched_col] = col_data
                    except Exception as parse_err:
                        logging.warning(f"Failed to parse schema_updates JSON block: {parse_err}")
                else:
                    visible_text = full_response.split("Here's a thinking process:")[0].strip()
                    if not visible_text:
                        visible_text = "Task completed."
                full_response = visible_text
            elif "<<<SCHEMA_UPDATES>>>" in full_response and "<<<END>>>" in full_response:
                parts = full_response.split("<<<SCHEMA_UPDATES>>>")
                visible_text = parts[0].strip()
                json_block = parts[1].split("<<<END>>>")[0].strip()
                if json_block.startswith("```"):
                    json_block = re.sub(r"^```[a-z]*", "", json_block).rstrip("`").strip()
                try:
                    schema_updates = json.loads(json_block)
                    # Apply updates
                    for col, col_data in schema_updates.items():
                        matched_col = next((c for c in session_data["column_actions"] if c.lower() == col.lower()), col)
                        session_data["column_actions"][matched_col] = col_data
                except Exception as parse_err:
                    logging.warning(f"Failed to parse schema_updates JSON block: {parse_err}")
                full_response = visible_text
            
            # Safety net: Extract actions & fuzzy match columns directly from user message
            msg_lower = message.lower()
            is_drop = any(kw in msg_lower for kw in ["drop", "remove", "delete", "eliminate"])
            is_keep = any(kw in msg_lower for kw in ["keep", "retain", "include"])
            is_trans = any(kw in msg_lower for kw in ["transform", "tranform", "convert", "encode", "replace", "change", "impute", "->", "=>", "to"])
            is_execute_cmd = any(kw in msg_lower for kw in ["perform", "perfrom", "execute", "run", "do task", "apply", "do it", "clean dataset", "process data"])

            for col in session_data["column_actions"].keys():
                # Fuzzy column match (handles UK/US spelling, singular/plural, spaces)
                if match_column_name(col, message):
                    if is_drop and session_data["column_actions"][col].get("action") != "drop":
                        upd = {"action": "drop", "reason": f"Dropped column '{col}' per user chat request.", "transformation": None}
                        schema_updates[col] = upd
                        session_data["column_actions"][col] = upd
                    elif is_keep and session_data["column_actions"][col].get("action") != "keep":
                        upd = {"action": "keep", "reason": f"Retained column '{col}' per user chat request.", "transformation": None}
                        schema_updates[col] = upd
                        session_data["column_actions"][col] = upd
                    elif is_trans or not is_drop:
                        polished_trans = polish_and_standardize_prompt(message, list(session_data["column_actions"].keys()))
                        upd = {"action": "transform", "reason": f"Transformed column '{col}' per user chat request.", "transformation": polished_trans}
                        schema_updates[col] = upd
                        session_data["column_actions"][col] = upd

        except Exception as e:
            logging.error(f"Streaming chat error: {str(e)}")
            msg_lower = message.lower()
            is_drop = any(kw in msg_lower for kw in ["drop", "remove", "delete", "eliminate"])
            is_keep = any(kw in msg_lower for kw in ["keep", "retain", "include"])
            is_trans = any(kw in msg_lower for kw in ["transform", "tranform", "convert", "encode", "replace", "change", "impute", "->", "=>", "to"])
            is_execute_cmd = any(kw in msg_lower for kw in ["perform", "perfrom", "execute", "run", "do task", "apply", "do it", "clean dataset", "process data"])

            for col in session_data["column_actions"].keys():
                if match_column_name(col, message):
                    if is_drop:
                        upd = {"action": "drop", "reason": f"Dropped column '{col}' per user chat request.", "transformation": None}
                        schema_updates[col] = upd
                        session_data["column_actions"][col] = upd
                    elif is_keep:
                        upd = {"action": "keep", "reason": f"Retained column '{col}' per user chat request.", "transformation": None}
                        schema_updates[col] = upd
                        session_data["column_actions"][col] = upd
                    elif is_trans or not is_drop:
                        polished_trans = polish_and_standardize_prompt(message, list(session_data["column_actions"].keys()))
                        upd = {"action": "transform", "reason": f"Transformed column '{col}' per user chat request.", "transformation": polished_trans}
                        schema_updates[col] = upd
                        session_data["column_actions"][col] = upd

            if not full_response:
                full_response = f"I have processed your request for the dataset: {message}."

        # Emit schema updates event (frontend UI badges and tables listen to this)
        trigger = (len(schema_updates) > 0) or is_execute_cmd
        yield f"event: schema_updates\ndata: {json.dumps({'schema_updates': schema_updates, 'column_actions': session_data['column_actions'], 'trigger_reprocess': trigger})}\n\n"

        # Save to session DB
        session_data["chat_history"].append({"role": "assistant", "content": full_response})
        save_session(session_data)

        # Auto-trigger background dataset re-process if schema changed or execution requested
        if trigger:
            t = threading.Thread(
                target=run_background_process,
                args=(current_app._get_current_object(), session_id, api_key),
                daemon=True
            )
            t.start()

        # Final done event
        yield f"event: done\ndata: {json.dumps({'full_message': full_response})}\n\n"

    generator = run_local_fallback_stream() if (is_mock or not client) else run_ai_stream()

    return Response(
        stream_with_context(generator),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )

# PDF Generation Endpoint
@api_blueprint.route('/api/sessions/<session_id>/pdf', methods=['POST'])
def create_pdf_report(session_id):
    if not reportlab_installed:
        return jsonify({"error": "ReportLab library is not properly installed or imported."}), 500

    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    if not session_data.get("cleaned_filename"):
        return jsonify({"error": "No cleaned file exists for this session. Please apply cleaning rules and process the dataset first."}), 400

    cleaned_path = os.path.join(current_app.config['OUTPUT_FOLDER'], session_data["cleaned_filename"])
    if not os.path.exists(cleaned_path):
        return jsonify({"error": "Cleaned data file not found"}), 404

    try:
        df = pd.read_excel(cleaned_path)

        # 1. Render Matplotlib charts to file with thread lock safety
        from powerbi_visuals.trend_charts import PLOT_LOCK

        chart_images = []
        target_charts = session_data.get("pinned_charts") if session_data.get("pinned_charts") else session_data.get("charts", [])
        for idx, chart in enumerate(target_charts):
            chart_type = chart.get("chart_type") or chart.get("type", "bar")
            title = chart.get("title") or f"{chart.get('y_axis', '')} by {chart.get('x_axis', '')}"
            x = chart.get("x_axis") or chart.get("x_col")
            y = chart.get("y_axis") or chart.get("y_col")

            if x not in df.columns:
                continue

            with PLOT_LOCK:
                try:
                    plt.figure(figsize=(6, 3.5))

                    # Setup Lora Font if registered, else DejaVu Sans
                    active_font = 'Lora' if 'Lora' in pdfmetrics.getRegisteredFontNames() else 'DejaVu Sans'
                    plt.title(title, fontname=active_font, fontsize=12, fontweight='bold', pad=10)

                    if chart_type == 'histogram':
                        df[x].dropna().value_counts().head(10).plot(kind='bar', color='#6366f1')
                        plt.ylabel('Frequency')
                    elif chart_type == 'pie':
                        df[x].dropna().value_counts().head(6).plot(kind='pie', autopct='%1.1f%%', colors=['#6366f1', '#a855f7', '#10b981', '#f59e0b', '#3b82f6'])
                        plt.ylabel('')
                    elif chart_type == 'scatter' and y in df.columns:
                        df.dropna(subset=[x, y]).plot(kind='scatter', x=x, y=y, color='#a855f7')
                    elif chart_type == 'line' and y in df.columns:
                        df.dropna(subset=[x, y]).sort_values(by=x).plot(kind='line', x=x, y=y, color='#6366f1')
                    elif chart_type == 'bar' and y in df.columns:
                        df.groupby(x)[y].mean().head(12).plot(kind='bar', color='#10b981')
                        plt.ylabel(f'Avg {y}')
                    else:
                        df[x].dropna().value_counts().head(10).plot(kind='bar', color='#6366f1')

                    plt.xticks(rotation=45, ha='right', fontsize=8)
                    plt.tight_layout()

                    img_filename = f"{session_id}_chart_{idx}.png"
                    img_path = os.path.join(current_app.config['OUTPUT_FOLDER'], img_filename)
                    plt.savefig(img_path, dpi=200, bbox_inches='tight')
                    chart_images.append((img_path, chart.get("description", "")))
                except Exception as plot_ex:
                    logging.warning(f"Failed to generate plot for PDF {title}: {str(plot_ex)}")
                finally:
                    plt.close()

        # 2. Build PDF Document using ReportLab & Lora Font
        pdf_filename = f"report_{session_id}.pdf"
        pdf_path = os.path.join(current_app.config['OUTPUT_FOLDER'], pdf_filename)

        font_regular = 'Lora' if 'Lora' in pdfmetrics.getRegisteredFontNames() else 'Helvetica'
        font_bold = 'Lora-Bold' if 'Lora-Bold' in pdfmetrics.getRegisteredFontNames() else 'Helvetica-Bold'

        doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()

        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Normal'],
            fontName=font_bold,
            fontSize=22,
            leading=26,
            textColor=colors.HexColor('#0f172a'),
            spaceAfter=6
        )

        subtitle_style = ParagraphStyle(
            'DocSubtitle',
            parent=styles['Normal'],
            fontName=font_regular,
            fontSize=11,
            leading=15,
            textColor=colors.HexColor('#64748b'),
            spaceAfter=20
        )

        h1_style = ParagraphStyle(
            'SectionH1',
            parent=styles['Normal'],
            fontName=font_bold,
            fontSize=14,
            leading=18,
            textColor=colors.HexColor('#4f46e5'),
            spaceBefore=12,
            spaceAfter=8,
            keepWithNext=True
        )

        body_style = ParagraphStyle(
            'DocBody',
            parent=styles['Normal'],
            fontName=font_regular,
            fontSize=9.5,
            leading=13.5,
            textColor=colors.HexColor('#334155'),
            spaceAfter=6
        )

        table_header_style = ParagraphStyle(
            'TableHeader',
            parent=styles['Normal'],
            fontName=font_bold,
            fontSize=8.5,
            leading=10.5,
            textColor=colors.HexColor('#ffffff')
        )

        table_cell_style = ParagraphStyle(
            'TableCell',
            parent=styles['Normal'],
            fontName=font_regular,
            fontSize=8.5,
            leading=10.5,
            textColor=colors.HexColor('#334155')
        )

        story = []

        # Cover header
        story.append(Paragraph("AI-Powered Data Cleansing & Diagnostics Report", title_style))
        story.append(Paragraph(f"Goal: {session_data['goal']}", subtitle_style))
        story.append(Spacer(1, 10))

        # Summary
        story.append(Paragraph("1. Executive Summary", h1_style))
        summary_text = (
            f"This diagnostics report details the cleaning operations performed on dataset "
            f"<b>{session_data['original_filename']}</b>. Guided by user goals and Nvidia GLM-5.2 "
            f"recommendations, duplicate/redundant structures were dropped, datatypes were normalized, "
            f"and missing values imputed."
        )
        story.append(Paragraph(summary_text, body_style))
        story.append(Spacer(1, 8))

        # Summary table
        initial_rows = session_data.get("row_count", 0)
        initial_cols = len(session_data.get("columns", []))
        final_rows = len(df)
        final_cols = len(df.columns)

        metric_data = [
            [Paragraph("Dimension", table_header_style), Paragraph("Original Dataset", table_header_style), Paragraph("Cleaned Dataset", table_header_style)],
            [Paragraph("Total Rows", table_cell_style), Paragraph(str(initial_rows), table_cell_style), Paragraph(str(final_rows), table_cell_style)],
            [Paragraph("Total Features / Columns", table_cell_style), Paragraph(str(initial_cols), table_cell_style), Paragraph(str(final_cols), table_cell_style)],
        ]
        metric_table = Table(metric_data, colWidths=[200, 160, 160])
        metric_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4f46e5')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('PADDING', (0,0), (-1,-1), 6),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        story.append(metric_table)
        story.append(Spacer(1, 15))

        # Section 2: Actions Table
        story.append(Paragraph("2. Applied Feature Rules", h1_style))
        schema_data = [
            [Paragraph("Column", table_header_style), Paragraph("Action", table_header_style), Paragraph("Explanation & Custom Rules", table_header_style)]
        ]
        for col, act in session_data.get("column_actions", {}).items():
            action_lbl = act.get("action", "keep").upper()
            reason_txt = act.get("reason", "")
            trans_txt = act.get("transformation")
            if trans_txt:
                reason_txt += f" (Transformation: {trans_txt})"
            schema_data.append([
                Paragraph(col, table_cell_style),
                Paragraph(action_lbl, table_cell_style),
                Paragraph(reason_txt, table_cell_style)
            ])
        schema_table = Table(schema_data, colWidths=[120, 80, 320])
        schema_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#0f172a')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        story.append(schema_table)

        story.append(PageBreak())  # Move description stats & charts to next page

        # Section 3: Stats
        story.append(Paragraph("3. Cleaned Dataset Descriptive Statistics", h1_style))
        desc_df = df.describe().round(2).reset_index()
        desc_cols = list(desc_df.columns)
        if len(desc_cols) > 6:
            desc_df = desc_df.iloc[:, :6]
            desc_cols = list(desc_df.columns)

        desc_header = [Paragraph(c, table_header_style) for c in desc_cols]
        desc_table_data = [desc_header]
        for _, row in desc_df.iterrows():
            row_cells = []
            for c in desc_cols:
                row_cells.append(Paragraph(str(row[c]), table_cell_style))
            desc_table_data.append(row_cells)

        col_w = 520 / len(desc_cols)
        desc_table = Table(desc_table_data, colWidths=[col_w] * len(desc_cols))
        desc_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#475569')),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('PADDING', (0,0), (-1,-1), 5),
            ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ]))
        story.append(desc_table)
        story.append(Spacer(1, 15))

        # Section 4: Charts
        story.append(Paragraph("4. Diagnostic Visualizations", h1_style))
        for img_path, desc in chart_images:
            story.append(Paragraph(desc, body_style))
            story.append(Spacer(1, 4))
            story.append(Image(img_path, width=380, height=220))
            story.append(Spacer(1, 12))

        doc.build(story)

        # Save pdf name to session record
        session_data["pdf_filename"] = pdf_filename

        # Log to chat
        pdf_chat_msg = f"I've compiled a professional PDF data diagnostics report using the **Lora** font. You can download it directly here: <br><a href='/api/sessions/{session_id}/download_pdf' class='btn btn-emerald' style='margin-top:0.5rem; padding: 0.4rem 1rem; font-size: 0.8rem;'><i class='fa-solid fa-file-pdf'></i> Download PDF Report</a>"
        session_data["chat_history"].append({"role": "assistant", "content": pdf_chat_msg})
        save_session(session_data)

        return jsonify({
            "success": True,
            "pdf_url": f"/api/sessions/{session_id}/download_pdf",
            "chat_history": session_data["chat_history"]
        })

    except Exception as e:
        logging.error(f"Error compiling PDF: {str(e)}")
        return jsonify({"error": f"Failed to generate PDF: {str(e)}"}), 500

@api_blueprint.route('/api/sessions/<session_id>/download_pdf', methods=['GET'])
def download_pdf_report(session_id):
    session_data = load_session(session_id)
    if not session_data or not session_data.get("pdf_filename"):
        return jsonify({"error": "PDF report not found. Please click generate report first."}), 404

    safe_pdf_name = secure_filename(session_data["pdf_filename"])
    pdf_path = os.path.join(current_app.config['OUTPUT_FOLDER'], safe_pdf_name)
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Report PDF file not found on disk."}), 404

    return send_from_directory(current_app.config['OUTPUT_FOLDER'], safe_pdf_name, as_attachment=True)


@api_blueprint.route('/api/sessions/<session_id>/pin_chart', methods=['POST'])
def toggle_pin_chart(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    data = request.json or {}
    chart_obj = data.get("chart")
    if not chart_obj:
        return jsonify({"error": "Missing chart payload"}), 400

    pinned = session_data.get("pinned_charts", [])
    
    chart_title = chart_obj.get("title") or f"{chart_obj.get('chart_type')}_{chart_obj.get('x_axis')}_{chart_obj.get('y_axis')}"
    
    existing_idx = -1
    for i, item in enumerate(pinned):
        item_id = item.get("title") or f"{item.get('chart_type')}_{item.get('x_axis')}_{item.get('y_axis')}"
        if item_id == chart_title:
            existing_idx = i
            break

    if existing_idx >= 0:
        pinned.pop(existing_idx)
        is_pinned = False
        message = "Unpinned chart from PDF report"
    else:
        pinned.append(chart_obj)
        is_pinned = True
        message = "Pinned chart to PDF report!"

    session_data["pinned_charts"] = pinned
    save_session(session_data)
    
    return jsonify({
        "success": True,
        "is_pinned": is_pinned,
        "pinned_count": len(pinned),
        "message": message
    })


@api_blueprint.route('/api/sessions/<session_id>/pinned_charts', methods=['GET'])
def get_pinned_charts(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
    pinned = session_data.get("pinned_charts", [])
    return jsonify({"pinned_charts": pinned, "count": len(pinned)})


@api_blueprint.route('/api/sessions/<session_id>/update_cell', methods=['POST'])
def update_individual_cell(session_id):
    """
    Directly updates a single cell in the dataset by row_index, column_name, and new_value.
    """
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    data = request.json or {}
    row_idx = data.get("row_index")
    col_name = data.get("column_name")
    new_val = data.get("new_value")

    if row_idx is None or not col_name:
        return jsonify({"error": "Missing row_index or column_name"}), 400

    file_id = session_data.get("file_id")
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_id)
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    try:
        sheet_name = session_data.get("sheet_name", 0)
        file_ext = file_id.rsplit('.', 1)[1].lower()
        if file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name not in ("Default", None) else 0)
        else:
            df = pd.read_csv(file_path)

        row_i = int(row_idx)
        if col_name in df.columns and 0 <= row_i < len(df):
            # Smart Type Auto-Inference: Cast input to column's underlying data type
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

            # Save non-destructively to session working copy in OUTPUT_FOLDER
            working_filename = f"edited_{file_id.split('.')[0]}.xlsx"
            working_path = os.path.join(current_app.config['OUTPUT_FOLDER'], working_filename)
            df.to_excel(working_path, index=False)
            session_data["cleaned_filename"] = working_filename
            save_session(session_data)

            # Trigger background process to reprocess dataset preview
            t = threading.Thread(
                target=run_background_process,
                args=(current_app._get_current_object(), session_id, None),
                daemon=True
            )
            t.start()

            return jsonify({"success": True, "message": f"Updated cell at row {row_i}, column '{col_name}' to '{casted_val}'"})
        else:
            return jsonify({"error": "Invalid row index or column name"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to update cell: {str(e)}"}), 500


@api_blueprint.route('/api/download/<filename>')
def download_cleaned_file(filename):
    safe_filename = secure_filename(filename)
    return send_from_directory(current_app.config['OUTPUT_FOLDER'], safe_filename, as_attachment=True)

@api_blueprint.route('/api/sessions/<session_id>/viz_chat', methods=['POST'])
def generate_viz_chat(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    data = request.json or {}
    message = data.get("message", "")
    api_key = data.get("api_key")
    provider = data.get("provider") or os.environ.get("LLM_PROVIDER")
    model = data.get("model") or os.environ.get("LLM_MODEL") or "llama-3.1-8b-instant"
    base_url = data.get("base_url")

    if not message:
        return jsonify({"error": "Missing message"}), 400

    col_objs = session_data.get("columns", [])
    columns = [col["name"] for col in col_objs]

    def build_fallback_params(msg_text):
        msg_lower = msg_text.lower()
        cat = "comparison"
        c_type = "bar"

        if any(kw in msg_lower for kw in ["pie", "donut"]):
            cat = "part_to_whole"
            c_type = "pie" if "pie" in msg_lower else "donut"
        elif any(kw in msg_lower for kw in ["line", "trend", "area"]):
            cat = "trend"
            c_type = "line" if "line" in msg_lower else "area"
        elif any(kw in msg_lower for kw in ["scatter", "relationship", "bubble"]):
            cat = "relationship"
            c_type = "scatter"
        elif any(kw in msg_lower for kw in ["histogram", "distribution", "box"]):
            cat = "distribution"
            c_type = "histogram" if "histogram" in msg_lower else "box"
        elif any(kw in msg_lower for kw in ["waterfall", "funnel"]):
            cat = "change_flow"
            c_type = "waterfall" if "waterfall" in msg_lower else "funnel"

        matched_cols = []
        for col_name in columns:
            if re.search(rf"\b{re.escape(col_name.lower())}\b", msg_lower):
                matched_cols.append(col_name)

        x_col = matched_cols[0] if len(matched_cols) > 0 else (columns[0] if columns else "Category")
        y_col = matched_cols[1] if len(matched_cols) > 1 else (columns[-1] if columns else "Value")

        return {
            "chart_category": cat,
            "chart_type": c_type,
            "x_col": x_col,
            "y_col": y_col
        }

    client = get_llm_client(api_key=api_key, provider=provider, model=model, base_url=base_url)
    if not client:
        return jsonify({"success": True, "params": build_fallback_params(message)})

    system_prompt = f"""You are an AI data visualization assistant.
The user wants to generate a chart. You must extract the parameters for the chart based on the user's request.
The available columns in the dataset are: {', '.join(columns)}

You must return a JSON object with EXACTLY these keys:
- "chart_category": one of ["trend", "comparison", "part_to_whole", "relationship", "distribution", "single_metric", "geo", "tabular", "change_flow", "scheduling", "interactivity"]
- "chart_type": a specific type for the category (e.g. "bar", "line", "pie", "scatter", "histogram", "clustered_column", "waterfall", "donut")
- "x_col": The column name for the category or X-axis (for pie/donut charts, this is the label). Must be one of the available columns.
- "y_col": The column name for the value or Y-axis (for pie/donut charts, this is the value to sum). Must be one of the available columns.
- "y_col_2": (Optional) The secondary Y axis.
- "group_col": (Optional) The column name to group/color by.

Example for 'show me a bar chart of msrp by year':
{{"chart_category": "comparison", "chart_type": "bar", "x_col": "Model_Year", "y_col": "Base_MSRP"}}

Return ONLY valid JSON. No markdown formatting or extra text."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message}
            ],
            temperature=0
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:-3]
        elif content.startswith("```"):
            content = content[3:-3]

        result = json.loads(content)
        return jsonify({"success": True, "params": result})
    except Exception as e:
        logging.warning(f"LLM viz_chat failed ({str(e)}), using rule-based visual fallback.")
        return jsonify({"success": True, "params": build_fallback_params(message)})


@api_blueprint.route('/api/sessions/<session_id>/custom_chart', methods=['POST'])
def generate_custom_chart(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
        
    data = request.json or {}
    chart_category = data.get("chart_category")
    chart_type = data.get("chart_type")
    
    # Extract columns needed
    x_col = data.get("x_col")
    y_col = data.get("y_col")
    y_col_2 = data.get("y_col_2")
    group_col = data.get("group_col")
    filters = data.get("filters", {})

    
    # Load dataset (prefer cleaned file, fallback to raw upload file)
    clean_filename = session_data.get("cleaned_filename")
    if clean_filename:
        file_path = os.path.join(current_app.config['OUTPUT_FOLDER'], clean_filename)
    else:
        raw_file_id = session_data.get("file_id")
        if not raw_file_id:
            return jsonify({"error": "Dataset file not found."}), 400
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], raw_file_id)

    try:
        sheet_name = session_data.get("sheet_name", "Default")
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name != "Default" else 0)
    except Exception as e:
        return jsonify({"error": f"Failed to load dataset: {str(e)}"}), 500

    # Auto-resolve x_col and y_col if missing or invalid
    if not x_col or x_col not in df.columns:
        cat_cols = df.select_dtypes(include=['object', 'category', 'string']).columns.tolist()
        x_col = cat_cols[0] if cat_cols else df.columns[0]
    if not y_col or y_col not in df.columns:
        num_cols = df.select_dtypes(include=['number']).columns.tolist()
        y_col = num_cols[0] if num_cols else df.columns[-1]

    # Ensure y_col is numeric for plotting (strip symbols, coerce strings, fallback to count metric if purely text)
    if y_col and y_col in df.columns:
        if df[y_col].dtype == object or str(df[y_col].dtype) in ['category', 'string']:
            cleaned_num = df[y_col].astype(str).str.replace(r'[\$,%\s,]', '', regex=True)
            num_series = pd.to_numeric(cleaned_num, errors='coerce')
            if num_series.notna().sum() > 0:
                df[y_col] = num_series.fillna(0)
            else:
                df['_freq_metric'] = 1
                y_col = '_freq_metric'
        else:
            df[y_col] = pd.to_numeric(df[y_col], errors='coerce').fillna(0)

    if y_col_2 and y_col_2 in df.columns:
        cleaned_num2 = df[y_col_2].astype(str).str.replace(r'[\$,%\s,]', '', regex=True)
        df[y_col_2] = pd.to_numeric(cleaned_num2, errors='coerce').fillna(0)

    # Apply filters (slicer simulation)
    for col, f_val in filters.items():
        if col in df.columns:
            if isinstance(f_val, dict):
                # E.g. {">": 10}
                for op, v in f_val.items():
                    if op == '>': df = df[df[col] > v]
                    elif op == '<': df = df[df[col] < v]
                    elif op == '>=': df = df[df[col] >= v]
                    elif op == '<=': df = df[df[col] <= v]
                    elif op == '==': df = df[df[col] == v]
            else:
                # Exact match
                df = df[df[col] == f_val]

    if df.empty:
        return jsonify({"error": "Filtered dataset is empty."}), 400

    # DoS Protection & Memory Safety: Pre-aggregate or sample large DataFrames before plotting
    max_plot_points = 1000
    if chart_category in ['comparison', 'part_to_whole']:
        # Aggregate categorical metrics to top 30 categories
        if x_col in df.columns and y_col in df.columns:
            try:
                agg_cols = [y_col]
                if y_col_2 and y_col_2 in df.columns and y_col_2 != y_col:
                    agg_cols.append(y_col_2)
                
                # Perform grouped mean aggregation if cardinality is high
                if df[x_col].nunique() > 30 or len(df) > 100:
                    grouped_df = df.groupby(x_col, as_index=False)[agg_cols].mean().head(30)
                    if not grouped_df.empty:
                        df = grouped_df
            except Exception as agg_ex:
                logging.warning(f"Chart pre-aggregation fallback: {agg_ex}")
    elif len(df) > max_plot_points:
        # Uniform downsampling for continuous line/scatter/distribution charts
        step = len(df) // max_plot_points
        df = df.iloc[::step].copy()

    try:
        result = None
        
        # Dispatch to the correct module based on category and type
        if chart_category == 'trend':
            import powerbi_visuals.trend_charts as tc
            if chart_type == 'line': result = tc.render_line_chart(df, x_col, y_col)
            elif chart_type == 'area': result = tc.render_area_chart(df, x_col, y_col)
            elif chart_type == 'column': result = tc.render_column_chart(df, x_col, y_col)
            elif chart_type == 'combo': result = tc.render_combo_chart(df, x_col, y_col, y_col_2)
            
        elif chart_category == 'comparison':
            import powerbi_visuals.comparison_charts as cc
            if chart_type == 'bar': result = cc.render_bar_chart(df, x_col, y_col)
            elif chart_type == 'clustered_column': result = cc.render_clustered_column_chart(df, x_col, y_col, y_col_2)
            
        elif chart_category == 'part_to_whole':
            import powerbi_visuals.part_to_whole_charts as ptc
            if chart_type == 'pie': result = ptc.render_pie_chart(df, x_col, y_col)
            elif chart_type == 'donut': result = ptc.render_donut_chart(df, x_col, y_col)
            elif chart_type == 'stacked_column': result = ptc.render_stacked_column_chart(df, x_col, group_col, y_col)
            elif chart_type == '100_stacked_column': result = ptc.render_100_stacked_column_chart(df, x_col, group_col, y_col)
            elif chart_type == 'treemap': result = ptc.render_treemap(df, x_col, y_col)
            elif chart_type == 'sunburst': result = ptc.render_sunburst_chart(df, [x_col, group_col] if group_col else [x_col], y_col)
            
        elif chart_category == 'change_flow':
            import powerbi_visuals.change_flow_charts as cfc
            if chart_type == 'waterfall': result = cfc.render_waterfall_chart(df, x_col, y_col)
            elif chart_type == 'funnel': result = cfc.render_funnel_chart(df, x_col, y_col)
            elif chart_type == 'sankey': result = cfc.render_sankey_diagram(df, x_col, group_col, y_col)
            elif chart_type == 'ribbon': result = cfc.render_ribbon_chart(df, x_col, group_col, y_col)
            
        elif chart_category == 'relationship':
            import powerbi_visuals.relationship_charts as rc
            if chart_type == 'scatter': result = rc.render_scatter_chart(df, x_col, y_col)
            elif chart_type == 'bubble': result = rc.render_bubble_chart(df, x_col, y_col, y_col_2)
            elif chart_type == 'key_influencers': result = rc.render_key_influencers(df, y_col)
            
        elif chart_category == 'distribution':
            import powerbi_visuals.distribution_charts as dc
            if chart_type == 'histogram': result = dc.render_histogram(df, x_col)
            elif chart_type == 'box': result = dc.render_box_and_whisker(df, y_col, x_col)
            
        elif chart_category == 'single_metric':
            import powerbi_visuals.single_metric_visuals as smv
            if chart_type == 'card': result = smv.render_card(df, y_col)
            elif chart_type == 'multi_row_card': result = smv.render_multi_row_card(df, x_col, y_col)
            elif chart_type == 'gauge': result = smv.render_gauge_chart(df, y_col)
            
        elif chart_category == 'geo':
            import powerbi_visuals.geo_charts as gc
            if chart_type == 'bubble_map': result = gc.render_bubble_map(df, x_col, y_col, y_col_2, group_col)
            elif chart_type == 'choropleth': result = gc.render_choropleth_map(df, x_col, y_col)
            
        elif chart_category == 'tabular':
            import powerbi_visuals.tabular_visuals as tv
            if chart_type == 'table': result = tv.render_table(df)
            elif chart_type == 'matrix': result = tv.render_matrix(df, x_col, group_col, y_col)
            
        elif chart_category == 'scheduling':
            import powerbi_visuals.time_based_scheduling as tbs
            if chart_type == 'gantt': result = tbs.render_gantt_chart(df, group_col, x_col, y_col)
            elif chart_type == 'calendar_heatmap': result = tbs.render_calendar_heatmap(df, x_col, y_col)
            
        elif chart_category == 'interactivity':
            import powerbi_visuals.interactivity as ic
            if chart_type == 'smart_narrative': result = ic.render_smart_narrative(df, x_col, y_col)
            
        if not result:
            return jsonify({"error": "Unsupported chart type or category"}), 400
            
        return jsonify({"success": True, "chart": result})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Error generating chart: {str(e)}"}), 500




@api_blueprint.route('/api/sessions/<session_id>/dry_run', methods=['POST'])
def dry_run_session(session_id):
    """
    Dry-run endpoint: Builds and validates a cleaning plan without modifying the dataset on disk.
    """
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    data = request.json or {}
    actions = data.get("actions") or session_data.get("column_actions", {})
    sheet_name = data.get("sheet_name", "Default")

    file_id = session_data["file_id"]
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_id)
    if not os.path.exists(file_path):
        return jsonify({"error": "Uploaded file not found"}), 404

    try:
        file_ext = file_id.rsplit('.', 1)[1].lower()
        if file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name != "Default" else 0)
        else:
            df = pd.read_csv(file_path)

        from services.cleaning import build_cleaning_plan, validate_plan

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
        return jsonify({
            "success": True,
            "cleaning_plan": full_plan,
            "validation": val_results
        })
    except Exception as e:
        return jsonify({"error": f"Dry run failed: {str(e)}"}), 500

