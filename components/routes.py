import os
import uuid
import json
import logging
import datetime
import threading
from flask import Blueprint, request, jsonify, send_from_directory, current_app, Response, stream_with_context
from werkzeug.utils import secure_filename
import pandas as pd
import numpy as np

# Services
from services.ai_service import get_openai_client
from services.data_service import (
    summarize_schema,
    generate_mock_recommendations,
    generate_mock_charts,
    run_background_process
)

# Utils
from utils.helpers import allowed_file, parse_json_response
from utils.session_manager import load_session, save_session
from utils.fonts import download_lora_fonts
from utils.job_tracker import _set_job_state, _get_job_state

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
    from reportlab.pdfbase.ttfonts import TTFont
    reportlab_installed = True
except ImportError:
    reportlab_installed = False

# Initialize blueprint
api_blueprint = Blueprint('api', __name__)

@api_blueprint.route('/')
def index():
    return send_from_directory('static', 'index.html')

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

            preview_data = df.head(5).fillna("").to_dict(orient='records')

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
    file_id = session_data["file_id"]
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], file_id)
    if not os.path.exists(file_path):
        return jsonify({"error": "Uploaded file not found"}), 404

    is_mock = (api_key == "MOCK")
    client = None if is_mock else get_openai_client(api_key)

    if not is_mock and not client:
        return jsonify({"error": "Nvidia API key is required. Please set it in the settings panel."}), 400

    try:
        file_ext = file_id.rsplit('.', 1)[1].lower()
        if file_ext in ['xlsx', 'xls']:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name != "Default" else 0)
        else:
            df = pd.read_csv(file_path)

        if is_mock:
            recommendations = generate_mock_recommendations(df, goal)
            # Save mapping to session
            col_actions = {r["column"]: {"action": r["action"], "reason": r["reason"], "transformation": r["transformation"]} for r in recommendations}
            session_data["column_actions"] = col_actions

            intro_msg = f"Goal set: **{goal}**.<br>Using mock offline recommendations. I suggest dropping redundant columns. You can edit the suggestions in the grid."
            session_data["chat_history"].append({"role": "user", "content": f"My data cleaning goal is: {goal}"})
            session_data["chat_history"].append({"role": "assistant", "content": intro_msg})
            save_session(session_data)

            return jsonify({
                "recommendations": recommendations,
                "chat_history": session_data["chat_history"]
            })

        schema_summary = summarize_schema(df, max_samples=1)
        prompt = f"""
You are a brilliant Data Scientist and AI cleaning agent.
The user wants to prepare a dataset for the following specific Goal:
"{goal}"

Here is the dataset schema summary:
{json.dumps(schema_summary, indent=2)}

Analyze each column and recommend whether to KEEP, DROP, or TRANSFORM it.
Follow these rules:
1. Recommend dropping columns that are completely empty, have redundant or duplicate information, consist of random identifiers/hashes (unless key for joins), or are entirely irrelevant to the user's Goal.
2. Recommend keeping columns that are direct features, logical targets, or highly relevant context for the Goal.
3. Recommend transforming columns if they contain dates that need parsing, categorical strings that require encoding, or numbers stored as strings, or if they have substantial missing values.
4. Provide a clear, educational explanation for each recommendation.

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
        logging.info("Requesting column recommendations from Nvidia GLM-5.2...")
        try:
            completion = client.chat.completions.create(
                model="z-ai/glm-5.2",
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
            save_session(session_data)

            return jsonify({
                "recommendations": recommendations,
                "chat_history": session_data["chat_history"]
            })
        except Exception as api_err:
            logging.error(f"Nvidia API call failed, falling back to mock: {str(api_err)}")
            recommendations = generate_mock_recommendations(df, goal)
            col_actions = {r["column"]: {"action": r["action"], "reason": r["reason"], "transformation": r["transformation"]} for r in recommendations}
            session_data["column_actions"] = col_actions

            fallback_msg = f"Goal set: **{goal}**.<br>⚠️ Nvidia API unavailable. Using offline recommendations fallback."
            session_data["chat_history"].append({"role": "user", "content": f"My data cleaning goal is: {goal}"})
            session_data["chat_history"].append({"role": "assistant", "content": fallback_msg})
            save_session(session_data)

            return jsonify({
                "recommendations": recommendations,
                "chat_history": session_data["chat_history"],
                "warning": f"Nvidia API is currently experiencing issues ({str(api_err)}). Falling back to local offline recommendations."
            })

    except Exception as e:
        logging.error(f"Error during AI analysis: {str(e)}")
        return jsonify({"error": f"AI analysis failed: {str(e)}"}), 500

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

        columns_to_drop = []
        columns_to_keep = []
        transform_actions = []

        session_data["column_actions"] = actions  # Save approved action choices

        for col, col_data in actions.items():
            action = col_data.get('action')
            trans = col_data.get('transformation')

            if col not in df.columns:
                continue

            if action == 'drop':
                columns_to_drop.append(col)
            elif action == 'transform':
                columns_to_keep.append(col)
                try:
                    if trans and ('date' in trans.lower() or 'time' in trans.lower()):
                        df[col] = pd.to_datetime(df[col], errors='coerce')
                    elif trans and ('numeric' in trans.lower() or 'number' in trans.lower() or 'float' in trans.lower() or 'int' in trans.lower()):
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                        if 'impute' in trans.lower() or 'fill' in trans.lower() or 'missing' in trans.lower():
                            df[col] = df[col].fillna(df[col].median())
                    elif pd.api.types.is_numeric_dtype(df[col]):
                        if df[col].isnull().any():
                            df[col] = df[col].fillna(df[col].median())
                    else:
                        if df[col].isnull().any():
                            df[col] = df[col].fillna("Unknown")
                    transform_actions.append(f"Transformed '{col}': {trans or 'imputed missing values'}")
                except Exception as ex:
                    logging.warning(f"Failed to transform column {col}: {str(ex)}")
                    transform_actions.append(f"Failed to transform '{col}': {str(ex)}")
            else:
                columns_to_keep.append(col)
                try:
                    if pd.api.types.is_numeric_dtype(df[col]):
                        if df[col].isnull().any():
                            df[col] = df[col].fillna(df[col].median())
                    else:
                        if df[col].isnull().any():
                            df[col] = df[col].fillna("Unknown")
                except Exception:
                    pass

        if columns_to_drop:
            df = df.drop(columns=columns_to_drop)

        final_shape = df.shape

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
            "transformations_applied": transform_actions
        }

        # Do not generate visualizations during clean processing. Visualizations will be requested separately.
        session_data["charts"] = []
        rendered_charts = []
        charts = []  # Explicitly defined to prevent NameError in refactored code
        for chart in charts:
            chart_type = chart.get("chart_type")
            title = chart.get("title")
            x_col = chart.get("x_axis")
            y_col = chart.get("y_axis")
            desc = chart.get("description")

            if x_col not in df.columns:
                continue

            chart_item = {
                "chart_type": chart_type,
                "title": title,
                "description": desc,
                "x_axis": x_col,
                "y_axis": y_col,
                "data": []
            }

            try:
                if chart_type == 'histogram':
                    value_counts = df[x_col].value_counts().head(10)
                    chart_item["labels"] = [str(x) for x in value_counts.index]
                    chart_item["values"] = [int(v) for v in value_counts.values]
                elif chart_type == 'pie':
                    value_counts = df[x_col].value_counts().head(6)
                    chart_item["labels"] = [str(x) for x in value_counts.index]
                    chart_item["values"] = [int(v) for v in value_counts.values]
                elif chart_type == 'scatter' and y_col in df.columns:
                    temp_df = df[[x_col, y_col]].dropna().head(100)
                    chart_item["points"] = [{"x": float(row[x_col]) if pd.api.types.is_numeric_dtype(df[x_col]) else str(row[x_col]),
                                             "y": float(row[y_col]) if pd.api.types.is_numeric_dtype(df[y_col]) else str(row[y_col])}
                                            for _, row in temp_df.iterrows()]
                elif chart_type == 'line' and y_col in df.columns:
                    temp_df = df[[x_col, y_col]].dropna().sort_values(by=x_col).head(50)
                    chart_item["labels"] = [str(x) for x in temp_df[x_col]]
                    chart_item["values"] = [float(y) if pd.api.types.is_numeric_dtype(df[y_col]) else str(y) for y in temp_df[y_col]]
                elif chart_type == 'bar':
                    if y_col in df.columns:
                        if df[x_col].nunique() < 15:
                            grouped = df.groupby(x_col)[y_col].mean().head(15)
                            chart_item["labels"] = [str(x) for x in grouped.index]
                            chart_item["values"] = [float(v) for v in grouped.values]
                            chart_item["title"] = f"{title} (Average)"
                        else:
                            temp_df = df[[x_col, y_col]].dropna().head(15)
                            chart_item["labels"] = [str(x) for x in temp_df[x_col]]
                            chart_item["values"] = [float(y) if pd.api.types.is_numeric_dtype(df[y_col]) else str(y) for y in temp_df[y_col]]
                    else:
                        value_counts = df[x_col].value_counts().head(15)
                        chart_item["labels"] = [str(x) for x in value_counts.index]
                        chart_item["values"] = [int(v) for v in value_counts.values]

                rendered_charts.append(chart_item)
            except Exception as chart_data_ex:
                logging.warning(f"Error computing data for chart {title}: {str(chart_data_ex)}")

        preview_data = df.head(10).fillna("").to_dict(orient='records')

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

# Poll endpoint — frontend polls this every 2s to detect completion
@api_blueprint.route('/api/sessions/<session_id>/status', methods=['GET'])
def get_processing_status(session_id):
    job = _get_job_state(session_id)
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

    is_mock = (api_key == "MOCK")
    client = None if is_mock else get_openai_client(api_key)

    def run_local_fallback(msg_lower, current_session):
        schema_updates = {}
        columns = [col["name"] for col in current_session["columns"]]
        for col in columns:
            if col.lower() in msg_lower:
                if any(kw in msg_lower for kw in ["drop", "remove", "delete", "eliminate"]):
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

        logging.info("Sending chat query to Nvidia GLM-5.2...")
        completion = client.chat.completions.create(
            model="z-ai/glm-5.2",
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

    is_mock = (api_key == "MOCK")
    client = None if is_mock else get_openai_client(api_key)

    def run_local_fallback_stream():
        """Local rule-based fallback that emits SSE events."""
        msg_lower = message.lower()
        schema_updates = {}
        columns = [col["name"] for col in session_data["columns"]]
        for col in columns:
            if col.lower() in msg_lower:
                if any(kw in msg_lower for kw in ["drop", "remove", "delete", "eliminate"]):
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

If the user asks for schema updates, include a JSON block at the end only:
<<<SCHEMA_UPDATES>>>
{{"column_name": {{"action": "drop|keep|transform", "reason": "...", "transformation": "... or null"}}}}
<<<END>>>

If no changes are needed, respond conversationally and omit the block."""

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
                model="z-ai/glm-5.2",
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

                # Don't stream the SCHEMA_UPDATES block to the user
                if "<<<SCHEMA_UPDATES>>>" not in full_response:
                    yield f"data: {json.dumps({'token': token})}\n\n"

            # Extract schema updates from the full response
            if "<<<SCHEMA_UPDATES>>>" in full_response and "<<<END>>>" in full_response:
                parts = full_response.split("<<<SCHEMA_UPDATES>>>")
                visible_text = parts[0].strip()
                json_block = parts[1].split("<<<END>>>")[0].strip()
                try:
                    schema_updates = json.loads(json_block)
                    # Apply updates
                    for col, col_data in schema_updates.items():
                        matched_col = next((c for c in session_data["column_actions"] if c.lower() == col.lower()), col)
                        session_data["column_actions"][matched_col] = col_data
                except Exception as parse_err:
                    logging.warning(f"Failed to parse schema_updates JSON block: {parse_err}")
                full_response = visible_text
            else:
                full_response = full_response.strip()

        except Exception as e:
            logging.error(f"Streaming chat failed: {str(e)}")
            # Fallback: local rule parsing
            msg_lower = message.lower()
            columns = [col["name"] for col in session_data["columns"]]
            for col in columns:
                if col.lower() in msg_lower:
                    if any(kw in msg_lower for kw in ["drop", "remove", "delete"]):
                        schema_updates[col] = {"action": "drop", "reason": "Dropped by user in chat (fallback).", "transformation": None}
                        session_data["column_actions"][col] = schema_updates[col]
                    elif any(kw in msg_lower for kw in ["keep", "retain", "include"]):
                        schema_updates[col] = {"action": "keep", "reason": "Kept by user in chat (fallback).", "transformation": None}
                        session_data["column_actions"][col] = schema_updates[col]
            full_response = f"⚠️ Streaming API unavailable ({str(e)[:60]}). Changes applied via local rule engine."
            yield f"data: {json.dumps({'token': full_response})}\n\n"

        # Emit schema updates event (even if empty – frontend always listens)
        trigger = len(schema_updates) > 0
        yield f"event: schema_updates\ndata: {json.dumps({'schema_updates': schema_updates, 'column_actions': session_data['column_actions'], 'trigger_reprocess': trigger})}\n\n"

        # Save to session DB
        session_data["chat_history"].append({"role": "assistant", "content": full_response})
        save_session(session_data)

        # Auto-trigger background re-process if schema changed
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

        # 1. Render Matplotlib charts to file
        chart_images = []
        for idx, chart in enumerate(session_data.get("charts", [])):
            chart_type = chart.get("chart_type")
            title = chart.get("title")
            x = chart.get("x_axis")
            y = chart.get("y_axis")

            if x not in df.columns:
                continue

            plt.figure(figsize=(6, 3.5))

            # Setup Lora Font if registered, else DejaVu Sans
            active_font = 'Lora' if 'Lora' in pdfmetrics.getRegisteredFontNames() else 'DejaVu Sans'
            plt.title(title, fontname=active_font, fontsize=12, fontweight='bold', pad=10)

            try:
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
                plt.savefig(img_path, dpi=200)
                plt.close()
                chart_images.append((img_path, chart.get("description", "")))
            except Exception as plot_ex:
                logging.warning(f"Failed to generate plot for PDF {title}: {str(plot_ex)}")
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

    pdf_path = os.path.join(current_app.config['OUTPUT_FOLDER'], session_data["pdf_filename"])
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Report PDF file not found on disk."}), 404

    return send_from_directory(current_app.config['OUTPUT_FOLDER'], session_data["pdf_filename"], as_attachment=True)

@api_blueprint.route('/api/download/<filename>')
def download_cleaned_file(filename):
    safe_filename = secure_filename(filename)
    return send_from_directory(current_app.config['OUTPUT_FOLDER'], safe_filename, as_attachment=True)
