"""
models/__init__.py
------------------
SQLAlchemy declarative Base and database engine/session utilities for Mercury.
"""
import os
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    create_engine,
    event,
    Column,
    String,
    Integer,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint
)
from sqlalchemy.orm import (
    declarative_base,
    sessionmaker,
    scoped_session,
    relationship
)
from sqlalchemy.types import TypeDecorator

import config

Base = declarative_base()

class JSONType(TypeDecorator):
    """Platform-independent JSON type that serializes dict/list to JSON string for SQLite."""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return json.loads(value)


class User(Base):
    __tablename__ = 'users'

    id = Column(String(36), primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(String(50), nullable=False)
    is_admin = Column(Integer, default=0)


    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "is_admin": bool(self.is_admin)
        }


class SessionModel(Base):
    __tablename__ = 'sessions'

    id = Column(String(36), primary_key=True)  # UUID
    owner_id = Column(String(36), nullable=True, index=True)
    name = Column(String(255), nullable=False)  # Display name
    original_filename = Column(String(255), nullable=False)
    file_id = Column(String(255), nullable=True)  # <uuid>.<ext> on disk
    file_type = Column(String(20), nullable=True)
    sheets = Column(JSONType, default=list)
    row_count = Column(Integer, default=0)
    col_count = Column(Integer, default=0)
    columns = Column(JSONType, default=list)
    preview = Column(JSONType, default=list)
    goal = Column(Text, default='')
    status = Column(String(50), default='idle')
    progress = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    result = Column(JSONType, nullable=True)
    bg_result = Column(JSONType, nullable=True)
    recommendations = Column(JSONType, nullable=True)
    quality_metrics = Column(JSONType, nullable=True)
    stats = Column(JSONType, nullable=True)
    charts = Column(JSONType, default=list)
    pinned_charts = Column(JSONType, default=list)
    cleaned_filename = Column(String(255), nullable=True)
    pdf_filename = Column(String(255), nullable=True)
    version = Column(Integer, default=1, nullable=False)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)
    last_accessed = Column(String(50), nullable=False, index=True)

    column_actions = relationship('ColumnActionModel', back_populates='session', cascade='all, delete-orphan')
    operation_logs = relationship('OperationLogModel', back_populates='session', cascade='all, delete-orphan')
    chat_messages = relationship('ChatMessageModel', back_populates='session', cascade='all, delete-orphan', order_by='ChatMessageModel.created_at')
    jobs = relationship('JobModel', back_populates='session', cascade='all, delete-orphan')

    def to_dict(self):
        """Converts SessionModel and its child relationships to a complete dict matching legacy JSON shape."""
        col_actions_dict = {}
        for ca in self.column_actions:
            col_actions_dict[ca.column_name] = {
                "action": ca.action,
                "reason": ca.reason or "",
                "transformation": ca.transformation
            }
            if ca.operations:
                col_actions_dict[ca.column_name]["operations"] = ca.operations

        chat_history = []
        for msg in self.chat_messages:
            m_dict = {"role": msg.role, "content": msg.content}
            if msg.reasoning_content:
                m_dict["reasoning_content"] = msg.reasoning_content
            chat_history.append(m_dict)

        audit_log = []
        for op in self.operation_logs:
            audit_log.append({
                "step": op.step_order,
                "column": op.column_name,
                "operation": op.operation,
                "status": op.status,
                "message": op.message,
                "details": op.details
            })

        return {
            "session_id": self.id,
            "owner_id": self.owner_id,
            "name": self.name,
            "original_filename": self.original_filename,
            "file_id": self.file_id,
            "file_type": self.file_type,
            "sheets": self.sheets or ["Default"],
            "row_count": self.row_count or 0,
            "col_count": self.col_count or 0,
            "columns": self.columns or [],
            "preview": self.preview or [],
            "goal": self.goal or "",
            "status": self.status or "idle",
            "progress": self.progress or 0,
            "error": self.error,
            "result": self.result,
            "bg_result": self.bg_result,
            "recommendations": self.recommendations or [],
            "column_actions": col_actions_dict,
            "chat_history": chat_history,
            "audit_log": audit_log,
            "quality_metrics": self.quality_metrics or {},
            "stats": self.stats or {},
            "charts": self.charts or [],
            "pinned_charts": self.pinned_charts or [],
            "cleaned_filename": self.cleaned_filename,
            "pdf_filename": self.pdf_filename,
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_accessed": self.last_accessed
        }


class ColumnActionModel(Base):
    __tablename__ = 'column_actions'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    column_name = Column(String(255), nullable=False)
    action = Column(String(50), default='keep')
    reason = Column(Text, nullable=True)
    transformation = Column(Text, nullable=True)
    operations = Column(JSONType, nullable=True)
    updated_at = Column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint('session_id', 'column_name', name='uq_session_column'),
    )

    session = relationship('SessionModel', back_populates='column_actions')


class OperationLogModel(Base):
    __tablename__ = 'operation_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    step_order = Column(Integer, default=0)
    column_name = Column(String(255), nullable=True)
    operation = Column(String(100), nullable=False)
    status = Column(String(50), default='success')
    message = Column(Text, nullable=True)
    details = Column(JSONType, nullable=True)
    created_at = Column(String(50), nullable=False)

    session = relationship('SessionModel', back_populates='operation_logs')


class ChatMessageModel(Base):
    __tablename__ = 'chat_messages'

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    reasoning_content = Column(JSONType, nullable=True)
    created_at = Column(String(50), nullable=False, index=True)

    session = relationship('SessionModel', back_populates='chat_messages')


class JobModel(Base):
    __tablename__ = 'jobs'

    id = Column(String(36), primary_key=True)  # UUID
    session_id = Column(String(36), ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    job_type = Column(String(50), default='analyze')  # analyze | process | pdf
    status = Column(String(50), default='queued')  # queued | running | succeeded | failed
    progress = Column(Integer, default=0)
    progress_msg = Column(String(255), nullable=True)
    error = Column(Text, nullable=True)
    result_payload = Column(JSONType, nullable=True)
    timeout_seconds = Column(Integer, default=300, nullable=False)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)

    session = relationship('SessionModel', back_populates='jobs')

    def to_dict(self):
        return {
            "job_id": self.id,
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "job_type": self.job_type,
            "type": self.job_type,
            "status": self.status,
            "progress": self.progress,
            "progress_msg": self.progress_msg,
            "error": self.error,
            "result": self.result_payload,
            "result_payload": self.result_payload,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }


# Global Engine & Session Factory
_engine = None
_SessionFactory = None

def get_engine(db_path: Optional[str] = None):
    global _engine
    if _engine is not None and db_path is None:
        return _engine

    target_path = db_path or getattr(config, 'DATABASE_PATH', os.path.join(os.getcwd(), 'users.db'))
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
    db_url = f"sqlite:///{os.path.abspath(target_path)}"

    engine = create_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 15}
    )

    # Enable WAL mode and foreign keys on SQLite connections
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    if db_path is None:
        _engine = engine
    return engine

def get_session_factory(db_path: Optional[str] = None):
    global _SessionFactory
    if _SessionFactory is not None and db_path is None:
        return _SessionFactory
    engine = get_engine(db_path)
    factory = scoped_session(sessionmaker(bind=engine, autoflush=False, autocommit=False))
    if db_path is None:
        _SessionFactory = factory
    return factory

def init_db(db_path: Optional[str] = None):
    """Creates all tables if they do not already exist, and migrates missing columns."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)

    # Lightweight SQLite column migration for existing tables
    try:
        with engine.connect() as conn:
            cursor = conn.connection.cursor()
            existing_cols = [r[1] for r in cursor.execute("PRAGMA table_info(jobs)").fetchall()]
            if 'user_id' not in existing_cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN user_id VARCHAR(36)")
                cursor.execute("CREATE INDEX IF NOT EXISTS ix_jobs_user_id ON jobs (user_id)")
            if 'timeout_seconds' not in existing_cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN timeout_seconds INTEGER DEFAULT 300 NOT NULL")
            conn.connection.commit()
            cursor.close()
    except Exception as e:
        logging.warning("jobs schema column sync note: %s", e)
