"""
repositories/session_repository.py
----------------------------------
Thread-safe, transaction-managed SQLAlchemy Repository for sessions,
chat messages, column actions, operation logs, and jobs.
"""
import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from flask import current_app

from sqlalchemy import select, update, delete
from sqlalchemy.orm import Session
from models import (
    get_session_factory,
    SessionModel,
    ColumnActionModel,
    ChatMessageModel,
    OperationLogModel,
    JobModel,
    User
)
import config

logger = logging.getLogger(__name__)


class SessionRepository:
    """Encapsulates all database persistence operations for session state."""

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or get_session_factory(config.DATABASE_PATH)

    def _get_db(self) -> Session:
        return self._session_factory()

    def get_by_id(self, session_id: str) -> Optional[dict]:
        """Loads session by UUID and returns serialized dictionary matching legacy JSON shape."""
        db = self._get_db()
        try:
            sess_obj = db.execute(
                select(SessionModel).where(SessionModel.id == session_id)
            ).scalar_one_or_none()
            if not sess_obj:
                return None
            return sess_obj.to_dict()
        finally:
            db.close()

    def list_by_owner(self, owner_id: Optional[str] = None, is_admin: bool = False) -> List[dict]:
        """Lists sessions for a specific user (or all if admin)."""
        db = self._get_db()
        try:
            query = select(SessionModel)
            if not is_admin:
                query = query.where(SessionModel.owner_id == owner_id)
            query = query.order_by(SessionModel.created_at.desc())
            results = db.execute(query).scalars().all()
            return [
                {
                    "session_id": s.id,
                    "name": s.name,
                    "original_filename": s.original_filename,
                    "goal": s.goal,
                    "created_at": s.created_at
                }
                for s in results
            ]
        finally:
            db.close()

    def count_by_owner(self, owner_id: str) -> int:
        """Returns the number of sessions owned by owner_id."""
        db = self._get_db()
        try:
            from sqlalchemy import func
            count = db.execute(
                select(func.count(SessionModel.id)).where(SessionModel.owner_id == owner_id)
            ).scalar()
            return count or 0
        finally:
            db.close()

    def save(self, data: dict) -> dict:
        """
        Creates or updates a session atomically.
        Handles optimistic locking version updates and synchronizes related tables.
        """
        if not data or 'session_id' not in data:
            raise ValueError("Session data must contain 'session_id'")

        session_id = data['session_id']
        db = self._get_db()
        try:
            now_str = datetime.now(timezone.utc).isoformat()
            sess_obj = db.execute(
                select(SessionModel).where(SessionModel.id == session_id)
            ).scalar_one_or_none()

            if sess_obj is None:
                # Create fresh session record
                sess_obj = SessionModel(
                    id=session_id,
                    owner_id=data.get('owner_id'),
                    name=data.get('name') or data.get('original_filename', 'Untitled'),
                    original_filename=data.get('original_filename', 'dataset.csv'),
                    file_id=data.get('file_id'),
                    file_type=data.get('file_type'),
                    sheets=data.get('sheets', ["Default"]),
                    row_count=data.get('row_count', 0),
                    col_count=data.get('col_count', 0),
                    columns=data.get('columns', []),
                    preview=data.get('preview', []),
                    goal=data.get('goal', ''),
                    status=data.get('status', 'idle'),
                    progress=data.get('progress', 0),
                    error=data.get('error'),
                    result=data.get('result'),
                    bg_result=data.get('bg_result'),
                    recommendations=data.get('recommendations', []),
                    quality_metrics=data.get('quality_metrics', {}),
                    stats=data.get('stats', {}),
                    charts=data.get('charts', []),
                    pinned_charts=data.get('pinned_charts', []),
                    cleaned_filename=data.get('cleaned_filename'),
                    pdf_filename=data.get('pdf_filename'),
                    version=1,
                    created_at=data.get('created_at') or now_str,
                    updated_at=now_str,
                    last_accessed=data.get('last_accessed') or now_str
                )
                db.add(sess_obj)
            else:
                # Update attributes with optimistic lock increment
                sess_obj.owner_id = data.get('owner_id', sess_obj.owner_id)
                sess_obj.name = data.get('name', sess_obj.name)
                sess_obj.original_filename = data.get('original_filename', sess_obj.original_filename)
                sess_obj.file_id = data.get('file_id', sess_obj.file_id)
                sess_obj.file_type = data.get('file_type', sess_obj.file_type)
                if 'sheets' in data: sess_obj.sheets = data['sheets']
                if 'row_count' in data: sess_obj.row_count = data['row_count']
                if 'col_count' in data: sess_obj.col_count = data['col_count']
                if 'columns' in data: sess_obj.columns = data['columns']
                if 'preview' in data: sess_obj.preview = data['preview']
                if 'goal' in data: sess_obj.goal = data['goal']
                if 'status' in data: sess_obj.status = data['status']
                if 'progress' in data: sess_obj.progress = data['progress']
                if 'error' in data: sess_obj.error = data['error']
                if 'result' in data: sess_obj.result = data['result']
                if 'bg_result' in data: sess_obj.bg_result = data['bg_result']
                if 'recommendations' in data: sess_obj.recommendations = data['recommendations']
                if 'quality_metrics' in data: sess_obj.quality_metrics = data['quality_metrics']
                if 'stats' in data: sess_obj.stats = data['stats']
                if 'charts' in data: sess_obj.charts = data['charts']
                if 'pinned_charts' in data: sess_obj.pinned_charts = data['pinned_charts']
                if 'cleaned_filename' in data: sess_obj.cleaned_filename = data['cleaned_filename']
                if 'pdf_filename' in data: sess_obj.pdf_filename = data['pdf_filename']
                sess_obj.version += 1
                sess_obj.updated_at = now_str
                if 'last_accessed' in data:
                    sess_obj.last_accessed = data['last_accessed']

            # Synchronize column_actions
            if 'column_actions' in data and isinstance(data['column_actions'], dict):
                existing_actions = {ca.column_name: ca for ca in sess_obj.column_actions}
                for col_name, col_dict in data['column_actions'].items():
                    if col_name in existing_actions:
                        ca_model = existing_actions[col_name]
                        ca_model.action = col_dict.get('action', 'keep')
                        ca_model.reason = col_dict.get('reason', '')
                        ca_model.transformation = col_dict.get('transformation')
                        ca_model.operations = col_dict.get('operations')
                        ca_model.updated_at = now_str
                    else:
                        ca_model = ColumnActionModel(
                            session_id=session_id,
                            column_name=col_name,
                            action=col_dict.get('action', 'keep'),
                            reason=col_dict.get('reason', ''),
                            transformation=col_dict.get('transformation'),
                            operations=col_dict.get('operations'),
                            updated_at=now_str
                        )
                        sess_obj.column_actions.append(ca_model)

            # Synchronize chat_history
            if 'chat_history' in data and isinstance(data['chat_history'], list):
                # Only sync chat messages if count differs to preserve incremental appends
                if len(sess_obj.chat_messages) != len(data['chat_history']):
                    db.execute(delete(ChatMessageModel).where(ChatMessageModel.session_id == session_id))
                    for idx, msg in enumerate(data['chat_history']):
                        msg_time = msg.get('created_at') or f"{now_str}_{idx:04d}"
                        sess_obj.chat_messages.append(ChatMessageModel(
                            session_id=session_id,
                            role=msg.get('role', 'user'),
                            content=msg.get('content', ''),
                            reasoning_content=msg.get('reasoning_content'),
                            created_at=msg_time
                        ))

            # Synchronize audit_log
            if 'audit_log' in data and isinstance(data['audit_log'], list):
                db.execute(delete(OperationLogModel).where(OperationLogModel.session_id == session_id))
                for idx, log_entry in enumerate(data['audit_log']):
                    sess_obj.operation_logs.append(OperationLogModel(
                        session_id=session_id,
                        step_order=log_entry.get('step', idx + 1),
                        column_name=log_entry.get('column'),
                        operation=log_entry.get('operation', 'unknown'),
                        status=log_entry.get('status', 'success'),
                        message=log_entry.get('message'),
                        details=log_entry.get('details'),
                        created_at=now_str
                    ))

            db.commit()
            return sess_obj.to_dict()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def append_chat_message(self, session_id: str, role: str, content: str, reasoning_content: Optional[dict] = None) -> dict:
        """
        Appends a single chat message row in an isolated transaction.
        Guarantees zero loss under concurrent multi-threaded writes.
        """
        db = self._get_db()
        try:
            now_str = datetime.now(timezone.utc).isoformat()
            msg = ChatMessageModel(
                session_id=session_id,
                role=role,
                content=content,
                reasoning_content=reasoning_content,
                created_at=now_str
            )
            db.add(msg)
            # Also touch parent session's updated_at
            db.execute(
                update(SessionModel)
                .where(SessionModel.id == session_id)
                .values(updated_at=now_str, last_accessed=now_str)
            )
            db.commit()
            return {"role": role, "content": content, "created_at": now_str}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def touch_last_accessed(self, session_id: str) -> None:
        """Updates last_accessed timestamp for TTL calculations."""
        db = self._get_db()
        try:
            now_str = datetime.now(timezone.utc).isoformat()
            db.execute(
                update(SessionModel)
                .where(SessionModel.id == session_id)
                .values(last_accessed=now_str)
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def delete(self, session_id: str) -> bool:
        """Deletes session and cascades deletion to child tables."""
        db = self._get_db()
        try:
            sess_obj = db.execute(
                select(SessionModel).where(SessionModel.id == session_id)
            ).scalar_one_or_none()
            if not sess_obj:
                return False
            db.delete(sess_obj)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def delete_by_owner(self, owner_id: str) -> List[str]:
        """Deletes all sessions belonging to owner_id and returns the list of deleted session IDs."""
        db = self._get_db()
        try:
            results = db.execute(
                select(SessionModel.id).where(SessionModel.owner_id == owner_id)
            ).scalars().all()
            session_ids = list(results)
            if session_ids:
                db.execute(delete(SessionModel).where(SessionModel.owner_id == owner_id))
                db.commit()
            return session_ids
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_expired_sessions(self, cutoff_iso: str) -> List[dict]:
        """Finds all sessions whose last_accessed is older than cutoff_iso."""
        db = self._get_db()
        try:
            results = db.execute(
                select(SessionModel).where(SessionModel.last_accessed < cutoff_iso)
            ).scalars().all()
            return [s.to_dict() for s in results]
        finally:
            db.close()


_repository_instance = None

def get_session_repository() -> SessionRepository:
    """Returns a SessionRepository using the current config.DATABASE_PATH (test-safe)."""
    # Always create fresh if the DB path has changed (e.g., in test fixtures)
    return SessionRepository(get_session_factory(config.DATABASE_PATH))
