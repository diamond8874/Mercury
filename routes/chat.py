"""
routes/chat.py
--------------
Blueprint for chat interactions: standard JSON chat and SSE streaming chat.
"""
import os
from flask import Blueprint, request, jsonify, current_app, Response, stream_with_context

from utils.auth import get_owned_session_or_404
from utils.url_validator import validate_base_url
from utils.limiter import limiter
from services.chat_service import handle_chat_turn, stream_chat_turn

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/api/sessions/<session_id>/chat', methods=['POST'])
@limiter.limit("60 per hour")
def chat_session(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    data = request.json or {}
    message = data.get("message")
    api_key = data.get("api_key")

    if not message:
        return jsonify({"error": "Missing message in request"}), 400

    provider = data.get("provider") or os.environ.get("LLM_PROVIDER")
    model = data.get("model") or os.environ.get("LLM_MODEL")
    base_url = data.get("base_url")

    if base_url:
        is_debug = current_app.config.get("DEBUG", False)
        valid, err = validate_base_url(base_url, is_debug=is_debug)
        if not valid:
            return jsonify({"error": f"Invalid base_url: {err}"}), 400

    if not model:
        return jsonify({"error": "No model specified and LLM_MODEL not set in environment"}), 400

    result = handle_chat_turn(
        session_data=session_data,
        message=message,
        api_key=api_key,
        provider=provider,
        model=model,
        base_url=base_url
    )
    return jsonify(result), 200


@chat_bp.route('/api/sessions/<session_id>/chat/stream', methods=['POST'])
@limiter.limit("60 per hour")
def chat_session_stream(session_id):
    session_data, err_resp = get_owned_session_or_404(session_id)
    if err_resp:
        return err_resp

    data = request.json or {}
    message = data.get("message", "")
    api_key = data.get("api_key")

    if not message:
        return jsonify({"error": "Missing message"}), 400

    provider = data.get("provider") or os.environ.get("LLM_PROVIDER")
    model = data.get("model") or os.environ.get("LLM_MODEL")
    base_url = data.get("base_url")

    if base_url:
        is_debug = current_app.config.get("DEBUG", False)
        valid, err = validate_base_url(base_url, is_debug=is_debug)
        if not valid:
            return jsonify({"error": f"Invalid base_url: {err}"}), 400

    session_data["chat_history"].append({"role": "user", "content": message})
    from utils.session_manager import save_session
    save_session(session_data)

    return Response(
        stream_with_context(
            stream_chat_turn(
                session_data=session_data,
                message=message,
                api_key=api_key,
                provider=provider,
                model=model,
                base_url=base_url
            )
        ),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'keep-alive'
        }
    )
