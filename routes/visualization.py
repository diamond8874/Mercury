"""
routes/visualization.py
-----------------------
Blueprint for chart recommendations, custom chart rendering, and pinned charts.
"""
import os
import pandas as pd
from flask import Blueprint, request, jsonify, current_app

from utils.auth import get_owned_session_or_404
from utils.session_manager import save_session
from utils.helpers import make_column_names_unique, read_csv_robust
from services.visualization_service import suggest_viz_params, render_dataset_chart

visualization_bp = Blueprint('visualization', __name__)


@visualization_bp.route('/api/sessions/<session_id>/viz_chat', methods=['POST'])
def generate_viz_chat(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    data = request.json or {}
    message = data.get("message", "")
    api_key = data.get("api_key")
    provider = data.get("provider") or os.environ.get("LLM_PROVIDER")
    model = data.get("model") or os.environ.get("LLM_MODEL") or "groq/openai/gpt-oss-120b"
    base_url = data.get("base_url")

    if not message:
        return jsonify({"error": "Missing message"}), 400

    col_objs = session_data.get("columns", [])
    columns = [col["name"] for col in col_objs]

    params = suggest_viz_params(
        message=message,
        columns=columns,
        api_key=api_key,
        provider=provider,
        model=model,
        base_url=base_url
    )
    return jsonify({"success": True, "params": params}), 200


@visualization_bp.route('/api/sessions/<session_id>/custom_chart', methods=['POST'])
def generate_custom_chart(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    data = request.json or {}
    chart_category = data.get("chart_category")
    chart_type = data.get("chart_type")
    x_col = data.get("x_col")
    y_col = data.get("y_col")
    y_col_2 = data.get("y_col_2")
    group_col = data.get("group_col")
    filters = data.get("filters", {})

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
            df = read_csv_robust(file_path)
        else:
            df = pd.read_excel(file_path, sheet_name=sheet_name if sheet_name != "Default" else 0)
        df = make_column_names_unique(df)
    except Exception as e:
        return jsonify({"error": f"Failed to load dataset: {str(e)}"}), 500

    result, err = render_dataset_chart(
        df=df,
        chart_category=chart_category,
        chart_type=chart_type,
        x_col=x_col,
        y_col=y_col,
        y_col_2=y_col_2,
        group_col=group_col,
        filters=filters
    )
    if err:
        err_msg, status_code = err
        return jsonify({"error": err_msg}), status_code

    return jsonify({"success": True, "chart": result}), 200


@visualization_bp.route('/api/sessions/<session_id>/pin_chart', methods=['POST'])
def toggle_pin_chart(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

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
    }), 200


@visualization_bp.route('/api/sessions/<session_id>/pinned_charts', methods=['GET'])
def get_pinned_charts(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp
    pinned = session_data.get("pinned_charts", [])
    return jsonify({"pinned_charts": pinned, "count": len(pinned)}), 200
