"""
services/cleaning — Structured AI Data Cleaning Engine
=======================================================
Public API:
    build_cleaning_plan(col, trans, df)  → list[dict]
    validate_plan(plan, df)              → list[dict] (validation results)
    execute_plan(plan, df)               → dict (df, audit_log, warnings, errors)
"""

from services.cleaning.intent_parser import build_cleaning_plan
from services.cleaning.validator import validate_plan
from services.cleaning.executor import execute_plan

__all__ = ["build_cleaning_plan", "validate_plan", "execute_plan"]
