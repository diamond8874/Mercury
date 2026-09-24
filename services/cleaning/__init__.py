"""
services/cleaning — Structured AI Data Cleaning Engine
=======================================================
Public API:
    run_cleaning_engine(df, actions)    → dict (df, audit_log, quality_metrics, stats, ...)
    build_cleaning_plan(col, trans, df) → list[dict]
    validate_plan(plan, df)             → list[dict] (validation results)
    execute_plan(plan, df)              → dict (df, audit_log, warnings, errors)
"""

from services.cleaning.intent_parser import build_cleaning_plan
from services.cleaning.validator import validate_plan
from services.cleaning.executor import execute_plan
from services.cleaning.engine import run_cleaning_engine
from services.cleaning.schema import (
    BaseOperation,
    DropColumnOp,
    KeepColumnOp,
    ReplaceValueOp,
    ImputeOp,
    NormalizeOp,
    EncodeOp,
    ParseDateOp,
    DropDuplicatesOp,
    ClipOutliersOp,
    LogTransformOp,
    ConvertTypeOp,
    RoundNumericOp,
    RenameColumnOp,
    StripWhitespaceOp,
    CaseTransformOp,
    ColumnRecommendation,
    CleaningPlanModel,
    parse_typed_operation,
    validate_operation_against_dataframe,
)

__all__ = [
    "run_cleaning_engine",
    "build_cleaning_plan",
    "validate_plan",
    "execute_plan",
    "BaseOperation",
    "DropColumnOp",
    "KeepColumnOp",
    "ReplaceValueOp",
    "ImputeOp",
    "NormalizeOp",
    "EncodeOp",
    "ParseDateOp",
    "DropDuplicatesOp",
    "ClipOutliersOp",
    "LogTransformOp",
    "ConvertTypeOp",
    "RoundNumericOp",
    "RenameColumnOp",
    "StripWhitespaceOp",
    "CaseTransformOp",
    "ColumnRecommendation",
    "CleaningPlanModel",
    "parse_typed_operation",
    "validate_operation_against_dataframe",
]
