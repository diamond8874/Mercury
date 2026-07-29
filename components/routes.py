"""
All REST + SSE endpoints, grouped by pipeline stage.

Stage order the UI follows:

    POST /api/upload                     -> reads the file, starts profiling
    GET  /api/sessions/<id>/status       -> "profiling" ... "profile_ready"
    POST /api/analyze                    -> only once the user submits a goal
    GET  /api/sessions/<id>/status       -> "analyzing" -> "analyze_done"
                                            -> "processing" -> "done"

No endpoint hardcodes a model or vendor: connection settings arrive per request
(``api_key`` / ``provider`` / ``model`` / ``base_url``) and are resolved by
``services.llm_provider``.
"""

import os
import uuid
import json
import logging
import datetime
import threading

from flask import (Blueprint, request, jsonify, send_from_directory,
                   current_app, Response, stream_with_context)
from werkzeug.utils import secure_filename
import pandas as pd

# Services
from services.llm_provider import (
    get_llm_client,
    llm_options_from_request,
    provider_catalog,
    resolve_llm_config,
)
from services.profile_service import (
    read_dataset,
    build_profile,
    run_background_profile,
)
from services.chart_service import (
    build_chart_payload,
    generate_ai_charts,
    render_chart_images,
    validate_chart_specs,
)
from services.data_service import (
    apply_actions,
    generate_recommendations,
    run_analysis_job,
    run_background_process,
)

# Utils
from utils.helpers import allowed_file, parse_json_response
from utils.session_manager import load_session, save_session
from utils.job_tracker import (
    _get_job_state,
    _set_job_state,
    clear_profile_ready,
    reset_job,
)

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, Image, PageBreak)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.pdfbase import pdfmetrics
    reportlab_installed = True
except ImportError:
    reportlab_installed = False

api_blueprint = Blueprint('api', __name__)

# Chat markers the model may append; they are stripped before display.
SCHEMA_MARKER_START, SCHEMA_MARKER_END = "<<<SCHEMA_UPDATES>>>", "<<<END>>>"
CHART_MARKER_START, CHART_MARKER_END = "<<<CHARTS>>>", "<<<END_CHARTS>>>"
CHART_INTENT_WORDS = ("chart", "plot", "graph", "visual", "histogram", "scatter",
                      "pie", "heatmap", "distribution", "correlation")


def _spawn(target, *args, **kwargs):
    """Start a daemon thread bound to the real app object (not the proxy)."""
    thread = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)
    thread.start()
    return thread


def _app():
    return current_app._get_current_object()


@api_blueprint.route('/')
def index():
    return send_from_directory('static', 'index.html')


# ===========================================================================
# Provider / model configuration
# ===========================================================================

@api_blueprint.route('/api/providers', methods=['GET'])
def list_providers():
    """
    Catalog of known providers plus whatever the server resolved from its own
    environment. The settings UI renders its dropdown from this, so adding a
    provider needs no front-end change.
    """
    server_default = resolve_llm_config()
    return jsonify({
        "providers": provider_catalog(),
        "server_default": server_default.public_dict(),
        "notes": "Any OpenAI-compatible endpoint works. Pick 'custom' and supply base_url for anything not listed.",
    })


@api_blueprint.route('/api/llm/verify', methods=['POST'])
def verify_llm():
    """Round-trip a tiny prompt so the user can confirm their key works."""
    data = request.json or {}
    client = get_llm_client(**llm_options_from_request(data))
    result = client.verify()
    return jsonify(result), (200 if result.get("ok") else 400)


@api_blueprint.route('/api/llm/models', methods=['POST'])
def list_llm_models():
    """List the models the supplied key can reach, when the provider exposes them."""
    data = request.json or {}
    client = get_llm_client(**llm_options_from_request(data))
    try:
        models = client.list_models()
        return jsonify({
            "provider": client.provider,
            "current_model": client.model,
            "models": models,
        })
    except Exception as exc:  # noqa: BLE001 - listing is optional everywhere
        return jsonify({
            "provider": client.provider,
            "current_model": client.model,
            "models": [],
            "error": str(exc)[:300],
        }), 200


# ===========================================================================
# Session CRUD
# ===========================================================================

@api_blueprint.route('/api/sessions', methods=['GET'])
def list_sessions():
    sessions = []
    session_folder = current_app.config['SESSION_FOLDER']
    for name in os.listdir(session_folder):
        # `<id>.job.json` is the job-state mirror, not a session record.
        if not name.endswith('.json') or name.endswith('.job.json'):
            continue
        try:
            with open(os.path.join(session_folder, name), 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            sessions.append({
                "session_id": data.get("session_id"),
                "name": data.get("name"),
                "original_filename": data.get("original_filename"),
                "goal": data.get("goal"),
                "created_at": data.get("created_at"),
            })
        except Exception:  # noqa: BLE001 - skip unreadable session files
            pass
    sessions.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return jsonify(sessions)


@api_blueprint.route('/api/sessions/<session_id>', methods=['GET'])
def get_session_detail(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
    session_data["job"] = _get_job_state(session_id)
    return jsonify(session_data)


@api_blueprint.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    for folder_key, filename in (
        ('UPLOAD_FOLDER', session_data.get("file_id")),
        ('OUTPUT_FOLDER', session_data.get("cleaned_filename")),
        ('OUTPUT_FOLDER', session_data.get("pdf_filename")),
    ):
        if not filename:
            continue
        try:
            path = os.path.join(current_app.config[folder_key], filename)
            if os.path.exists(path):
                os.remove(path)
        except OSError as exc:
            logging.warning(f"Could not remove {filename} during session delete: {exc}")

    path = os.path.join(current_app.config['SESSION_FOLDER'], f"{session_id}.json")
    if os.path.exists(path):
        os.remove(path)
    reset_job(session_id)
    return jsonify({"success": True})


# ===========================================================================
# Stage 1 - upload and read the dataset (no AI involved)
# ===========================================================================

@api_blueprint.route('/api/upload', methods=['POST'])
def upload_file():
    """
    Save the file, return light metadata immediately, and kick off deep
    profiling in the background.

    Deliberately does **not** call any model: the user has not stated a goal
    yet, so there is nothing to analyse. The response arrives as soon as the
    file parses, and profiling continues while the user types.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part in the request"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "Unsupported file format. Please upload Excel (.xlsx, .xls) or CSV."}), 400

    original_filename = secure_filename(file.filename)
    unique_id = str(uuid.uuid4())
    file_ext = original_filename.rsplit('.', 1)[1].lower()
    saved_filename = f"{unique_id}.{file_ext}"
    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], saved_filename)
    file.save(file_path)
    logging.info(f"File saved to {file_path}")

    try:
        sheets = ["Default"]
        if file_ext in ('xlsx', 'xls'):
            sheets = pd.ExcelFile(file_path).sheet_names
        df = read_dataset(file_path, file_ext, sheets[0] if file_ext in ('xlsx', 'xls') else None)

        num_rows, num_cols = df.shape
        columns = [{
            "name": str(col),
            "type": str(df[col].dtype),
            "null_count": int(df[col].isnull().sum()),
            "sample_values": [str(v) for v in df[col].dropna().head(3).tolist()],
        } for col in df.columns]
        preview_data = df.head(5).fillna("").astype(str).to_dict(orient='records')

        session_id = str(uuid.uuid4())
        session_data = {
            "session_id": session_id,
            "name": original_filename,
            "original_filename": original_filename,
            "file_id": saved_filename,
            "file_type": file_ext,
            "sheets": sheets,
            "sheet_name": sheets[0] if file_ext in ('xlsx', 'xls') else "Default",
            "row_count": int(num_rows),
            "col_count": int(num_cols),
            "columns": columns,
            "preview": preview_data,
            "profile": None,
            "goal": "",
            "column_actions": {},
            "chat_history": [{
                "role": "assistant",
                "content": (f"I've loaded `{original_filename}` - **{num_rows} rows x {num_cols} columns** - "
                            "and I'm profiling it in the background right now.<br>"
                            "Tell me what model you plan to train or what you want to learn from this data, "
                            "and I'll run the full analysis and build the charts."),
            }],
            "charts": [],
            "cleaned_filename": None,
            "created_at": datetime.datetime.now().isoformat(),
        }
        save_session(session_data)

        # Start reading/profiling straight away, without blocking this response.
        clear_profile_ready(session_id)
        _set_job_state(session_id, "profiling", phase="profile", progress=5,
                       progress_msg="Reading the uploaded dataset...")
        _spawn(run_background_profile, _app(), session_id, session_data["sheet_name"])

        return jsonify({
            "session_id": session_id,
            "file_id": saved_filename,
            "original_name": original_filename,
            "file_type": file_ext,
            "sheets": sheets,
            "row_count": int(num_rows),
            "col_count": int(num_cols),
            "columns": columns,
            "preview": preview_data,
            "chat_history": session_data["chat_history"],
            "profiling": True,
            "next_step": "Submit a goal to POST /api/analyze to start the AI analysis.",
        })

    except Exception as exc:  # noqa: BLE001
        logging.error(f"Error parsing uploaded file: {exc}")
        return jsonify({"error": f"Failed to parse Excel/CSV file: {exc}"}), 500


@api_blueprint.route('/api/sessions/<session_id>/profile', methods=['GET'])
def get_session_profile(session_id):
    """Return the cached dataset profile, or 202 while it is still being built."""
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    profile = session_data.get("profile")
    if not profile:
        job = _get_job_state(session_id)
        return jsonify({"status": job.get("status"), "progress": job.get("progress"),
                        "message": job.get("progress_msg") or "Profiling in progress."}), 202
    return jsonify(profile)


@api_blueprint.route('/api/sessions/<session_id>/sheet', methods=['POST'])
def set_active_sheet(session_id):
    """Switch the active Excel sheet and re-profile it in the background."""
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    sheet_name = (request.json or {}).get("sheet_name") or "Default"
    if sheet_name not in (session_data.get("sheets") or ["Default"]):
        return jsonify({"error": f"Unknown sheet '{sheet_name}'"}), 400

    session_data["sheet_name"] = sheet_name
    session_data["profile"] = None
    save_session(session_data)

    clear_profile_ready(session_id)
    _set_job_state(session_id, "profiling", phase="profile", progress=5,
                   progress_msg=f"Re-reading sheet '{sheet_name}'...")
    _spawn(run_background_profile, _app(), session_id, sheet_name)
    return jsonify({"status": "profiling", "sheet_name": sheet_name})


# ===========================================================================
# Stage 2 - analysis, which only starts once the user states a goal
# ===========================================================================

@api_blueprint.route('/api/analyze', methods=['POST'])
def analyze_schema():
    """
    Start the AI analysis for a stated goal.

    Asynchronous by default: returns ``202`` immediately and the browser polls
    ``/api/sessions/<id>/status``. The worker waits for background profiling to
    finish, produces recommendations, then chains into cleaning + charts.

    Pass ``{"wait": true}`` to run it inline and get the recommendations in the
    response body instead (used by tests and scripted clients).
    """
    data = request.json or {}
    session_id = data.get("session_id")
    goal = (data.get("goal") or "").strip()

    if not session_id or not goal:
        return jsonify({"error": "Missing session_id or goal in request"}), 400

    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], session_data.get("file_id", ""))
    if not os.path.exists(file_path):
        return jsonify({"error": "Uploaded file not found"}), 404

    if data.get("sheet_name") and data["sheet_name"] != "Default":
        session_data["sheet_name"] = data["sheet_name"]
        save_session(session_data)

    llm_opts = llm_options_from_request(data)

    if data.get("wait"):
        return _analyze_sync(session_id, session_data, goal, llm_opts, file_path)

    _set_job_state(session_id, "analyzing", phase="analyze", progress=3,
                   progress_msg="Queued - waiting for the dataset profile...")
    _spawn(run_analysis_job, _app(), session_id, goal, llm_opts,
           bool(data.get("chain_process", True)))

    return jsonify({
        "status": "analyzing",
        "session_id": session_id,
        "goal": goal,
        "poll_url": f"/api/sessions/{session_id}/status",
        "message": "Analysis started. Poll the status endpoint for progress.",
    }), 202


def _analyze_sync(session_id, session_data, goal, llm_opts, file_path):
    """Inline analysis path for ``{"wait": true}``."""
    try:
        df = read_dataset(file_path, session_data.get("file_type"),
                          session_data.get("sheet_name", "Default"))
        profile = session_data.get("profile") or build_profile(
            df, sheet_name=session_data.get("sheet_name"))
        session_data["profile"] = profile
        session_data["columns"] = profile["columns"]

        llm = get_llm_client(**llm_opts)
        recommendations, source, warning = generate_recommendations(llm, df, goal, profile)

        session_data["goal"] = goal
        session_data["column_actions"] = {
            r["column"]: {"action": r["action"], "reason": r["reason"],
                          "transformation": r["transformation"]}
            for r in recommendations
        }
        session_data["analysis_source"] = source
        session_data["llm"] = llm.config.public_dict()

        dropped = [r["column"] for r in recommendations if r["action"] == "drop"]
        message = (f"Goal set: **{goal}**.<br>I read {profile['shape']['rows']} rows before analysing "
                   f"and recommend dropping {len(dropped)} column(s). Analysed with {llm.describe}.")
        if warning:
            message += f"<br>⚠️ {warning}"
        session_data["chat_history"].append({"role": "user", "content": f"My data cleaning goal is: {goal}"})
        session_data["chat_history"].append({"role": "assistant", "content": message})
        save_session(session_data)

        payload = {
            "recommendations": recommendations,
            "column_actions": session_data["column_actions"],
            "chat_history": session_data["chat_history"],
            "source": source,
            "llm": llm.config.public_dict(),
        }
        if warning:
            payload["warning"] = warning
        _set_job_state(session_id, "analyze_done", phase="analyze", progress=100,
                       progress_msg="Recommendations ready.", result=payload)
        return jsonify(payload)

    except Exception as exc:  # noqa: BLE001
        logging.error(f"Synchronous analysis failed: {exc}")
        return jsonify({"error": f"AI analysis failed: {exc}"}), 500


# ===========================================================================
# Stage 3 - cleaning, charts and status
# ===========================================================================

@api_blueprint.route('/api/process', methods=['POST'])
def process_dataset():
    """Synchronous clean + chart build. The UI normally uses the async path."""
    data = request.json or {}
    session_id = data.get("session_id")
    actions = data.get("actions")

    if not session_id or not actions:
        return jsonify({"error": "Missing session_id or actions in request"}), 400

    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], session_data.get("file_id", ""))
    if not os.path.exists(file_path):
        return jsonify({"error": "Uploaded file not found"}), 404

    sheet_name = data.get("sheet_name") or session_data.get("sheet_name", "Default")

    try:
        df = read_dataset(file_path, session_data.get("file_type"), sheet_name)
        session_data["column_actions"] = actions
        cleaned_df, stats = apply_actions(df, actions)

        output_filename = f"cleaned_{str(session_data['file_id']).split('.')[0]}.xlsx"
        output_path = os.path.join(current_app.config['OUTPUT_FOLDER'], output_filename)
        cleaned_df.to_excel(output_path, index=False)
        session_data["cleaned_filename"] = output_filename

        llm = get_llm_client(**llm_options_from_request(data))
        chart_specs, chart_source = generate_ai_charts(llm, cleaned_df, session_data.get("goal"))
        rendered_charts = build_chart_payload(cleaned_df, chart_specs)
        session_data["charts"] = chart_specs
        session_data["chart_source"] = chart_source

        preview_data = cleaned_df.head(10).fillna("").astype(str).to_dict(orient='records')
        result = {
            "download_url": f"/api/download/{output_filename}",
            "stats": stats,
            "charts": rendered_charts,
            "preview": preview_data,
            "chart_source": chart_source,
        }
        session_data["bg_result"] = result
        session_data["chat_history"].append({
            "role": "assistant",
            "content": (f"Cleaning complete: **{stats['initial_cols']}** features reduced to "
                        f"**{stats['final_cols']}** signals, and I built {len(rendered_charts)} chart(s). "
                        "Download the clean file or open the Visualizations tab."),
        })
        save_session(session_data)
        _set_job_state(session_id, "done", phase="process", result=result,
                       progress=100, progress_msg="Done!")

        return jsonify({"success": True, "chat_history": session_data["chat_history"], **result})

    except Exception as exc:  # noqa: BLE001
        logging.error(f"Error processing dataset: {exc}")
        return jsonify({"error": f"Failed to clean and process dataset: {exc}"}), 500


@api_blueprint.route('/api/sessions/<session_id>/trigger_process', methods=['POST'])
def trigger_background_process(session_id):
    """Re-run cleaning + charts in the background with the current schema actions."""
    data = request.json or {}
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    if data.get("sheet_name") and data["sheet_name"] != "Default":
        session_data["sheet_name"] = data["sheet_name"]
    if "column_actions" in data:
        session_data["column_actions"] = data["column_actions"]
    elif "actions" in data:
        session_data["column_actions"] = data["actions"]
    save_session(session_data)

    _set_job_state(session_id, "processing", phase="process", progress=5,
                   progress_msg="Queued for cleaning...")
    _spawn(run_background_process, _app(), session_id, None, llm_options_from_request(data))
    return jsonify({"status": "processing", "message": "Background processing started."})


@api_blueprint.route('/api/sessions/<session_id>/status', methods=['GET'])
def get_processing_status(session_id):
    """
    Poll target for the whole pipeline.

    ``status`` is one of: idle, profiling, profile_ready, analyzing,
    analyze_done, processing, done, error.
    """
    return jsonify(_get_job_state(session_id))


@api_blueprint.route('/api/sessions/<session_id>/charts', methods=['POST'])
def regenerate_charts(session_id):
    """
    Rebuild the visualisations for the cleaned dataset.

    Optional ``instruction`` steers the model ("plot age against churn"), and
    optional ``specs`` lets a client pass explicit chart definitions.
    """
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
    if not session_data.get("cleaned_filename"):
        return jsonify({"error": "No cleaned dataset yet. Run the analysis first."}), 400

    cleaned_path = os.path.join(current_app.config['OUTPUT_FOLDER'], session_data["cleaned_filename"])
    if not os.path.exists(cleaned_path):
        return jsonify({"error": "Cleaned data file not found"}), 404

    data = request.json or {}
    df = pd.read_excel(cleaned_path)

    if data.get("specs"):
        specs = validate_chart_specs(data["specs"], df)
        source = "manual"
    else:
        goal = session_data.get("goal") or ""
        if data.get("instruction"):
            goal = f"{goal}. Specifically: {data['instruction']}"
        llm = get_llm_client(**llm_options_from_request(data))
        specs, source = generate_ai_charts(llm, df, goal)

    rendered = build_chart_payload(df, specs)
    session_data["charts"] = specs
    session_data["chart_source"] = source
    result = dict(session_data.get("bg_result") or {})
    result["charts"] = rendered
    session_data["bg_result"] = result
    save_session(session_data)

    return jsonify({"charts": rendered, "specs": specs, "source": source})


# ===========================================================================
# Chat
# ===========================================================================

def _schema_context(session_data):
    context = []
    for column in session_data.get("columns", []):
        name = column["name"]
        action = session_data.get("column_actions", {}).get(
            name, {"action": "keep", "reason": "Default", "transformation": None})
        context.append({
            "column": name,
            "type": column.get("type"),
            "kind": column.get("semantic_type"),
            "null_pct": column.get("null_pct", column.get("null_count")),
            "sample_values": column.get("sample_values", []),
            "current_action": action.get("action"),
            "transformation": action.get("transformation"),
        })
    return context


def _chat_system_prompt(session_data, streaming):
    profile = session_data.get("profile") or {}
    shape = profile.get("shape", {})
    prompt = f"""You are an expert Data Scientist and AI cleaning assistant working on a real dataset.

Goal: "{session_data.get('goal') or 'not stated yet'}"
Dataset: {shape.get('rows', '?')} rows x {shape.get('cols', '?')} columns, {profile.get('missing_pct', '?')}% missing cells.

Current columns and chosen actions:
{json.dumps(_schema_context(session_data), indent=2, default=str)[:6000]}
"""
    if streaming:
        prompt += f"""
If the user asks for schema changes, append this block at the very end:
{SCHEMA_MARKER_START}
{{"column_name": {{"action": "drop|keep|transform", "reason": "...", "transformation": "... or null"}}}}
{SCHEMA_MARKER_END}

If the user asks for a chart, plot or visualisation, append this block at the very end:
{CHART_MARKER_START}
{{"charts": [{{"chart_type": "histogram|bar|pie|line|scatter|box|correlation", "title": "...",
              "x_axis": "ExactColumn", "y_axis": "ExactColumn or null", "description": "..."}}]}}
{CHART_MARKER_END}

Otherwise reply conversationally and omit both blocks."""
    else:
        prompt += """
When the user asks for a schema change, answer with valid JSON only:
{"message": "Your human-friendly response.",
 "schema_updates": {"ExactColumnName": {"action": "keep|drop|transform",
                                        "reason": "...", "transformation": "... or null"}}}
If no changes are needed, return empty schema_updates {}."""
    return prompt


def _local_schema_parse(message, session_data):
    """Rule-based intent parser used whenever no live model is available."""
    lowered = message.lower()
    updates = {}
    for column in session_data.get("columns", []):
        name = column["name"]
        if name.lower() not in lowered:
            continue
        if any(word in lowered for word in ("drop", "remove", "delete", "eliminate", "exclude")):
            updates[name] = {"action": "drop", "reason": "Dropped by user request in chat.",
                             "transformation": None}
        elif any(word in lowered for word in ("keep", "retain", "include", "add back")):
            updates[name] = {"action": "keep", "reason": "Kept by user request in chat.",
                             "transformation": None}
        elif any(word in lowered for word in ("transform", "convert", "encode", "impute", "parse")):
            updates[name] = {"action": "transform", "reason": "Transform requested in chat.",
                             "transformation": "Custom transform requested in chat"}
    return updates


def _wants_charts(message):
    return any(word in message.lower() for word in CHART_INTENT_WORDS)


def _apply_chart_request(session_id, session_data, instruction, llm_opts):
    """Rebuild charts on request and return the Chart.js payload (or None)."""
    if not session_data.get("cleaned_filename"):
        return None
    cleaned_path = os.path.join(current_app.config['OUTPUT_FOLDER'], session_data["cleaned_filename"])
    if not os.path.exists(cleaned_path):
        return None
    try:
        df = pd.read_excel(cleaned_path)
        goal = f"{session_data.get('goal') or ''}. Specifically: {instruction}"
        llm = get_llm_client(**llm_opts)
        specs, source = generate_ai_charts(llm, df, goal)
        session_data["charts"] = specs
        session_data["chart_source"] = source
        return build_chart_payload(df, specs)
    except Exception as exc:  # noqa: BLE001
        logging.warning(f"Chart request from chat failed: {exc}")
        return None


@api_blueprint.route('/api/sessions/<session_id>/chat', methods=['POST'])
def chat_session(session_id):
    """Non-streaming chat. Same capabilities as the SSE route, one JSON response."""
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    data = request.json or {}
    message = data.get("message")
    if not message:
        return jsonify({"error": "Missing message in request"}), 400

    session_data["chat_history"].append({"role": "user", "content": message})
    llm_opts = llm_options_from_request(data)
    llm = get_llm_client(**llm_opts)

    def respond(response_msg, schema_updates):
        for column, action in schema_updates.items():
            matched = next((c for c in session_data["column_actions"]
                            if c.lower() == column.lower()), column)
            session_data["column_actions"][matched] = action
        session_data["chat_history"].append({"role": "assistant", "content": response_msg})
        save_session(session_data)
        return jsonify({
            "message": response_msg,
            "schema_updates": schema_updates,
            "column_actions": session_data["column_actions"],
            "chat_history": session_data["chat_history"],
            "llm": llm.config.public_dict(),
        })

    if not llm.is_live:
        schema_updates = _local_schema_parse(message, session_data)
        if schema_updates:
            response_msg = (f"Done! I've updated **{', '.join(schema_updates.keys())}**. "
                            "The schema grid on the right has been refreshed.")
        else:
            response_msg = (f"I'm here to help with your goal: **{session_data.get('goal') or 'not set yet'}**. "
                            "Ask me to keep, drop or transform any column by name, or ask for a chart.")
        return respond(response_msg, schema_updates)

    try:
        messages = [{"role": "system", "content": _chat_system_prompt(session_data, streaming=False)}]
        messages += [{"role": turn["role"], "content": turn["content"]}
                     for turn in session_data["chat_history"][:-1]]
        messages.append({"role": "user", "content": message})

        response_text = llm.chat(messages, temperature=0.2, max_tokens=1500, json_mode=True)
        try:
            parsed = parse_json_response(response_text)
            response_msg = parsed.get("message", "I have processed your request.")
            schema_updates = parsed.get("schema_updates", {}) or {}
        except (ValueError, TypeError, json.JSONDecodeError):
            response_msg, schema_updates = response_text.strip(), {}
        return respond(response_msg, schema_updates)

    except Exception as exc:  # noqa: BLE001
        logging.error(f"Chat call failed: {exc}")
        schema_updates = _local_schema_parse(message, session_data)
        response_msg = f"⚠️ {llm.describe} was unavailable. Applied local parsing instead."
        if schema_updates:
            response_msg += f" Updated: **{', '.join(schema_updates.keys())}**."
        else:
            response_msg += " Mention a column name with 'drop', 'keep' or 'transform' to make changes."
        return respond(response_msg, schema_updates)


@api_blueprint.route('/api/sessions/<session_id>/chat/stream', methods=['POST'])
def chat_session_stream(session_id):
    """
    Streaming chat over Server-Sent Events.

    Event types emitted:
      * default (no ``event:`` line) - ``{"token": "..."}`` text deltas
      * ``schema_updates`` - updated column actions, plus ``trigger_reprocess``
      * ``charts``         - freshly built Chart.js payloads
      * ``done``           - ``{"full_message": "..."}``
    """
    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404

    data = request.json or {}
    message = data.get("message", "")
    if not message:
        return jsonify({"error": "Missing message"}), 400

    session_data["chat_history"].append({"role": "user", "content": message})
    save_session(session_data)

    llm_opts = llm_options_from_request(data)
    llm = get_llm_client(**llm_opts)
    app_object = _app()

    def finish(full_message, schema_updates, chart_payload):
        """Emit the trailing events and persist the turn."""
        trigger = len(schema_updates) > 0
        yield (f"event: schema_updates\ndata: "
               f"{json.dumps({'schema_updates': schema_updates, 'column_actions': session_data['column_actions'], 'trigger_reprocess': trigger})}\n\n")
        if chart_payload:
            yield f"event: charts\ndata: {json.dumps({'charts': chart_payload})}\n\n"

        session_data["chat_history"].append({"role": "assistant", "content": full_message})
        save_session(session_data)

        if trigger:
            _set_job_state(session_id, "processing", phase="process", progress=5,
                           progress_msg="Applying your chat changes...")
            _spawn(run_background_process, app_object, session_id, None, llm_opts)

        yield f"event: done\ndata: {json.dumps({'full_message': full_message})}\n\n"

    def offline_stream():
        schema_updates = _local_schema_parse(message, session_data)
        for column, action in schema_updates.items():
            session_data["column_actions"][column] = action

        chart_payload = None
        if _wants_charts(message):
            chart_payload = _apply_chart_request(session_id, session_data, message, llm_opts)

        if schema_updates:
            response_msg = (f"Done! I've updated **{', '.join(schema_updates.keys())}**. "
                            "Reprocessing the dataset now.")
        elif chart_payload:
            response_msg = f"I rebuilt {len(chart_payload)} chart(s) for you - see the Visualizations tab."
        else:
            response_msg = (f"I'm here to help with your goal: **{session_data.get('goal') or 'not set yet'}**. "
                            "Mention a column with 'drop', 'keep' or 'transform', or ask me for a chart.")

        for word in response_msg.split(' '):
            yield f"data: {json.dumps({'token': word + ' '})}\n\n"
        yield from finish(response_msg, schema_updates, chart_payload)

    def live_stream():
        messages = [{"role": "system", "content": _chat_system_prompt(session_data, streaming=True)}]
        messages += [{"role": turn["role"], "content": turn["content"]}
                     for turn in session_data["chat_history"][:-1]]
        messages.append({"role": "user", "content": message})

        full_response = ""
        schema_updates = {}
        chart_payload = None
        emitted = 0

        try:
            for token in llm.stream_chat(messages, temperature=0.3, max_tokens=1500):
                full_response += token
                # Hold back everything from the first marker onwards.
                visible = full_response.split(SCHEMA_MARKER_START)[0].split(CHART_MARKER_START)[0]
                if len(visible) > emitted:
                    yield f"data: {json.dumps({'token': visible[emitted:]})}\n\n"
                    emitted = len(visible)

            schema_updates = _extract_block(full_response, SCHEMA_MARKER_START, SCHEMA_MARKER_END) or {}
            for column, action in schema_updates.items():
                matched = next((c for c in session_data["column_actions"]
                                if c.lower() == column.lower()), column)
                session_data["column_actions"][matched] = action

            chart_block = _extract_block(full_response, CHART_MARKER_START, CHART_MARKER_END)
            if chart_block and chart_block.get("charts"):
                chart_payload = _apply_explicit_charts(session_data, chart_block["charts"])
            elif _wants_charts(message) and not schema_updates:
                chart_payload = _apply_chart_request(session_id, session_data, message, llm_opts)

            full_response = full_response.split(SCHEMA_MARKER_START)[0].split(CHART_MARKER_START)[0].strip()
            if not full_response:
                full_response = "Updated - see the panel on the right."

        except Exception as exc:  # noqa: BLE001
            logging.error(f"Streaming chat failed: {exc}")
            schema_updates = _local_schema_parse(message, session_data)
            for column, action in schema_updates.items():
                session_data["column_actions"][column] = action
            full_response = (f"⚠️ {llm.describe} was unavailable ({str(exc)[:80]}). "
                             "Changes were applied with the local rule engine.")
            yield f"data: {json.dumps({'token': full_response})}\n\n"

        yield from finish(full_response, schema_updates, chart_payload)

    generator = offline_stream() if not llm.is_live else live_stream()
    return Response(
        stream_with_context(generator),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no', 'Connection': 'keep-alive'},
    )


def _extract_block(text, start_marker, end_marker):
    """Pull a JSON block out of a model response, or return None."""
    if start_marker not in text:
        return None
    tail = text.split(start_marker, 1)[1]
    body = tail.split(end_marker, 1)[0].strip()
    try:
        return parse_json_response(body)
    except Exception as exc:  # noqa: BLE001
        logging.warning(f"Could not parse {start_marker} block: {exc}")
        return None


def _apply_explicit_charts(session_data, specs):
    """Render chart specs the model produced inline during a chat turn."""
    if not session_data.get("cleaned_filename"):
        return None
    cleaned_path = os.path.join(current_app.config['OUTPUT_FOLDER'], session_data["cleaned_filename"])
    if not os.path.exists(cleaned_path):
        return None
    df = pd.read_excel(cleaned_path)
    valid = validate_chart_specs(specs, df)
    if not valid:
        return None
    session_data["charts"] = valid
    session_data["chart_source"] = "ai"
    return build_chart_payload(df, valid)


# ===========================================================================
# Reporting and downloads
# ===========================================================================

@api_blueprint.route('/api/sessions/<session_id>/pdf', methods=['POST'])
def create_pdf_report(session_id):
    if not reportlab_installed:
        return jsonify({"error": "ReportLab is not installed."}), 500

    session_data = load_session(session_id)
    if not session_data:
        return jsonify({"error": "Session not found"}), 404
    if not session_data.get("cleaned_filename"):
        return jsonify({"error": "No cleaned file exists for this session. Process the dataset first."}), 400

    cleaned_path = os.path.join(current_app.config['OUTPUT_FOLDER'], session_data["cleaned_filename"])
    if not os.path.exists(cleaned_path):
        return jsonify({"error": "Cleaned data file not found"}), 404

    try:
        df = pd.read_excel(cleaned_path)
        registered = pdfmetrics.getRegisteredFontNames()
        font_regular = 'Lora' if 'Lora' in registered else 'Helvetica'
        font_bold = 'Lora-Bold' if 'Lora-Bold' in registered else 'Helvetica-Bold'

        # Charts: reuse the saved plan, or build one now if the session predates it.
        specs = session_data.get("charts") or []
        if not specs:
            llm = get_llm_client(**llm_options_from_request(request.json or {}))
            specs, _ = generate_ai_charts(llm, df, session_data.get("goal"))
            session_data["charts"] = specs
        chart_images = render_chart_images(
            df, specs, current_app.config['OUTPUT_FOLDER'], session_id,
            font_name='Lora' if 'Lora' in registered else None)

        pdf_filename = f"report_{session_id}.pdf"
        pdf_path = os.path.join(current_app.config['OUTPUT_FOLDER'], pdf_filename)
        doc = SimpleDocTemplate(pdf_path, pagesize=letter, rightMargin=40,
                                leftMargin=40, topMargin=40, bottomMargin=40)
        styles = getSampleStyleSheet()

        def style(name, font, size, leading, color, **kwargs):
            return ParagraphStyle(name, parent=styles['Normal'], fontName=font, fontSize=size,
                                  leading=leading, textColor=colors.HexColor(color), **kwargs)

        title_style = style('DocTitle', font_bold, 22, 26, '#0f172a', spaceAfter=6)
        subtitle_style = style('DocSubtitle', font_regular, 11, 15, '#64748b', spaceAfter=20)
        h1_style = style('SectionH1', font_bold, 14, 18, '#4f46e5', spaceBefore=12,
                         spaceAfter=8, keepWithNext=True)
        body_style = style('DocBody', font_regular, 9.5, 13.5, '#334155', spaceAfter=6)
        header_style = style('TableHeader', font_bold, 8.5, 10.5, '#ffffff')
        cell_style = style('TableCell', font_regular, 8.5, 10.5, '#334155')

        def make_table(rows, widths, header_color):
            table = Table(rows, colWidths=widths)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(header_color)),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('PADDING', (0, 0), (-1, -1), 5),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#f8fafc'), colors.white]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e2e8f0')),
            ]))
            return table

        profile = session_data.get("profile") or {}
        llm_info = session_data.get("llm") or {}
        engine_label = (f"{llm_info.get('label') or llm_info.get('provider') or 'the offline rule engine'}"
                        + (f" / {llm_info['model']}" if llm_info.get('model') else ""))

        story = [
            Paragraph("AI-Powered Data Cleansing &amp; Diagnostics Report", title_style),
            Paragraph(f"Goal: {session_data.get('goal', 'Not specified')}", subtitle_style),
            Spacer(1, 10),
            Paragraph("1. Executive Summary", h1_style),
            Paragraph(
                f"This report documents the cleaning performed on <b>{session_data['original_filename']}</b>. "
                f"The dataset was read and profiled before any model was consulted; recommendations were then "
                f"produced by <b>{engine_label}</b> and applied with Pandas. Redundant structures were dropped, "
                f"datatypes normalised, and missing values imputed.", body_style),
            Spacer(1, 8),
        ]

        story.append(make_table([
            [Paragraph("Dimension", header_style), Paragraph("Original", header_style),
             Paragraph("Cleaned", header_style)],
            [Paragraph("Total Rows", cell_style),
             Paragraph(str(profile.get("shape", {}).get("rows", session_data.get("row_count", 0))), cell_style),
             Paragraph(str(len(df)), cell_style)],
            [Paragraph("Total Features / Columns", cell_style),
             Paragraph(str(profile.get("shape", {}).get("cols", len(session_data.get("columns", [])))), cell_style),
             Paragraph(str(len(df.columns)), cell_style)],
            [Paragraph("Missing Cells", cell_style),
             Paragraph(f"{profile.get('missing_pct', 0)}%", cell_style),
             Paragraph(f"{round(df.isnull().sum().sum() / max(df.size, 1) * 100, 2)}%", cell_style)],
        ], [200, 160, 160], '#4f46e5'))
        story.append(Spacer(1, 15))

        story.append(Paragraph("2. Applied Feature Rules", h1_style))
        schema_rows = [[Paragraph("Column", header_style), Paragraph("Action", header_style),
                        Paragraph("Explanation &amp; Custom Rules", header_style)]]
        for column, action in (session_data.get("column_actions") or {}).items():
            reason = action.get("reason", "")
            if action.get("transformation"):
                reason += f" (Transformation: {action['transformation']})"
            schema_rows.append([Paragraph(str(column), cell_style),
                                Paragraph(str(action.get("action", "keep")).upper(), cell_style),
                                Paragraph(reason, cell_style)])
        story.append(make_table(schema_rows, [120, 80, 320], '#0f172a'))
        story.append(PageBreak())

        story.append(Paragraph("3. Cleaned Dataset Descriptive Statistics", h1_style))
        try:
            describe = df.describe().round(2).reset_index()
            if len(describe.columns) > 6:
                describe = describe.iloc[:, :6]
            desc_columns = list(describe.columns)
            desc_rows = [[Paragraph(str(c), header_style) for c in desc_columns]]
            for _, row in describe.iterrows():
                desc_rows.append([Paragraph(str(row[c]), cell_style) for c in desc_columns])
            story.append(make_table(desc_rows, [520 / len(desc_columns)] * len(desc_columns), '#475569'))
        except Exception as exc:  # noqa: BLE001 - a dataset with no numerics has no describe()
            story.append(Paragraph(f"No numeric summary available ({exc}).", body_style))
        story.append(Spacer(1, 15))

        story.append(Paragraph("4. Diagnostic Visualizations", h1_style))
        if chart_images:
            for image_path, description in chart_images:
                if description:
                    story.append(Paragraph(description, body_style))
                    story.append(Spacer(1, 4))
                story.append(Image(image_path, width=380, height=215))
                story.append(Spacer(1, 12))
        else:
            story.append(Paragraph("No visualisations could be generated for this dataset.", body_style))

        doc.build(story)

        session_data["pdf_filename"] = pdf_filename
        session_data["chat_history"].append({
            "role": "assistant",
            "content": (f"I've compiled a {len(chart_images)}-figure PDF diagnostics report. "
                        f"<br><a href='/api/sessions/{session_id}/download_pdf' class='btn btn-emerald' "
                        "style='margin-top:0.5rem; padding: 0.4rem 1rem; font-size: 0.8rem;'>"
                        "<i class='fa-solid fa-file-pdf'></i> Download PDF Report</a>"),
        })
        save_session(session_data)

        return jsonify({
            "success": True,
            "pdf_url": f"/api/sessions/{session_id}/download_pdf",
            "charts_included": len(chart_images),
            "chat_history": session_data["chat_history"],
        })

    except Exception as exc:  # noqa: BLE001
        logging.error(f"Error compiling PDF: {exc}")
        return jsonify({"error": f"Failed to generate PDF: {exc}"}), 500


@api_blueprint.route('/api/sessions/<session_id>/download_pdf', methods=['GET'])
def download_pdf_report(session_id):
    session_data = load_session(session_id)
    if not session_data or not session_data.get("pdf_filename"):
        return jsonify({"error": "PDF report not found. Generate the report first."}), 404

    pdf_path = os.path.join(current_app.config['OUTPUT_FOLDER'], session_data["pdf_filename"])
    if not os.path.exists(pdf_path):
        return jsonify({"error": "Report PDF file not found on disk."}), 404
    return send_from_directory(current_app.config['OUTPUT_FOLDER'],
                               session_data["pdf_filename"], as_attachment=True)


@api_blueprint.route('/api/download/<filename>')
def download_cleaned_file(filename):
    return send_from_directory(current_app.config['OUTPUT_FOLDER'],
                               secure_filename(filename), as_attachment=True)
