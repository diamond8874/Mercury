"""
schema.py — Typed Pydantic Operations Schema for AI Data Cleaning
=================================================================
Defines strict, typed Pydantic models for all cleaning operations.
Replaces brittle substring matching with a typed, schema-validated execution plan.
"""

from typing import Any, Dict, List, Literal, Optional, Union, Annotated
from pydantic import BaseModel, Field, ConfigDict, model_validator
import pandas as pd
import numpy as np


class BaseOperation(BaseModel):
    """Base class for all typed cleaning operations."""
    model_config = ConfigDict(extra="ignore")
    operation: str
    column: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    message: Optional[str] = None

    def to_plan_dict(self) -> dict:
        """Convert to legacy/standard executor plan format."""
        params = dict(self.parameters)
        return {
            "column": self.column,
            "operation": self.operation,
            "parameters": params,
            "message": self.message or f"Apply operation '{self.operation}' on '{self.column}'."
        }


class DropColumnOp(BaseOperation):
    operation: Literal["drop_column"] = "drop_column"
    column: Optional[str] = None

    def to_plan_dict(self) -> dict:
        return {
            "column": self.column,
            "operation": "drop_column",
            "parameters": {},
            "message": f"Drop column '{self.column}'."
        }


class KeepColumnOp(BaseOperation):
    operation: Literal["keep_column"] = "keep_column"
    column: Optional[str] = None

    def to_plan_dict(self) -> dict:
        return {
            "column": self.column,
            "operation": "keep_column",
            "parameters": {},
            "message": f"Retain column '{self.column}' unchanged (no implicit imputation)."
        }


class ReplaceValueOp(BaseOperation):
    operation: Literal["replace_value"] = "replace_value"
    column: Optional[str] = None
    mapping: Optional[Dict[str, Any]] = None
    old: Optional[Any] = None
    new: Optional[Any] = None

    @model_validator(mode="after")
    def populate_params(self):
        if not self.parameters:
            self.parameters = {}
        if not self.mapping and "mapping" in self.parameters:
            self.mapping = self.parameters["mapping"]
        if self.mapping:
            self.parameters["mapping"] = self.mapping
        elif self.old is not None and self.new is not None:
            self.parameters["mapping"] = {str(self.old): self.new}
        return self

    def to_plan_dict(self) -> dict:
        mapping = self.mapping or self.parameters.get("mapping", {})
        if not mapping and self.old is not None and self.new is not None:
            mapping = {str(self.old): self.new}
        desc = ", ".join([f"'{k}'→'{v}'" for k, v in mapping.items()]) if mapping else "empty"
        return {
            "column": self.column,
            "operation": "replace_value_exact",
            "parameters": {"mapping": mapping},
            "message": f"Replace values in '{self.column}': {desc}."
        }


class ImputeOp(BaseOperation):
    operation: Literal["impute"] = "impute"
    column: Optional[str] = None
    method: Literal["mean", "median", "mode", "zero", "custom", "constant", "unknown"] = "median"
    fill_value: Optional[Any] = None

    def to_plan_dict(self) -> dict:
        op_map = {
            "mean": "impute_mean",
            "median": "impute_median",
            "mode": "impute_mode",
            "zero": "impute_zero",
            "custom": "impute_custom",
            "constant": "impute_custom",
            "unknown": "impute_custom"
        }
        canonical_op = op_map.get(self.method, "impute_median")
        params = {}
        if self.method in ("custom", "constant"):
            params["value"] = self.fill_value if self.fill_value is not None else "Unknown"
        elif self.method == "unknown":
            params["value"] = "Unknown"
        return {
            "column": self.column,
            "operation": canonical_op,
            "parameters": params,
            "message": f"Explicitly impute missing values in '{self.column}' using method '{self.method}'."
        }


class NormalizeOp(BaseOperation):
    operation: Literal["normalize"] = "normalize"
    column: Optional[str] = None
    method: Literal["minmax", "zscore", "robust"] = "minmax"

    def to_plan_dict(self) -> dict:
        canonical_op = "standardize_zscore" if self.method == "zscore" else "normalize_minmax"
        return {
            "column": self.column,
            "operation": canonical_op,
            "parameters": {},
            "message": f"Normalize '{self.column}' using '{self.method}' scaling."
        }


class EncodeOp(BaseOperation):
    operation: Literal["encode"] = "encode"
    column: Optional[str] = None
    method: Literal["one_hot", "ordinal", "frequency", "label"] = "one_hot"
    drop_first: bool = False

    def to_plan_dict(self) -> dict:
        canonical_op = {
            "one_hot": "one_hot_encode",
            "ordinal": "ordinal_encode",
            "frequency": "frequency_encode",
            "label": "label_encode"
        }.get(self.method, "one_hot_encode")
        return {
            "column": self.column,
            "operation": canonical_op,
            "parameters": {"drop_first": self.drop_first},
            "message": f"Encode categorical column '{self.column}' using {self.method} encoding."
        }


class ParseDateOp(BaseOperation):
    operation: Literal["parse_date"] = "parse_date"
    column: Optional[str] = None
    format: Optional[str] = None

    def to_plan_dict(self) -> dict:
        return {
            "column": self.column,
            "operation": "standardize_date_format",
            "parameters": {"format": self.format} if self.format else {},
            "message": f"Standardize and parse dates in '{self.column}'."
        }


class DropDuplicatesOp(BaseOperation):
    operation: Literal["drop_duplicates"] = "drop_duplicates"
    column: Optional[str] = None
    subset: Optional[List[str]] = None
    keep: Literal["first", "last", False] = "first"

    def to_plan_dict(self) -> dict:
        if self.subset:
            return {
                "column": self.column or (self.subset[0] if self.subset else None),
                "operation": "drop_duplicates_by_columns",
                "parameters": {"subset": self.subset, "keep": self.keep},
                "message": f"Drop duplicate rows based on subset {self.subset}, keep='{self.keep}'."
            }
        elif self.column:
            return {
                "column": self.column,
                "operation": "drop_duplicates_by_columns",
                "parameters": {"subset": [self.column], "keep": self.keep},
                "message": f"Drop duplicate rows based on column '{self.column}', keep='{self.keep}'."
            }
        else:
            return {
                "column": None,
                "operation": "drop_duplicates_full",
                "parameters": {"keep": self.keep},
                "message": f"Drop duplicate rows across entire dataset, keep='{self.keep}'."
            }


class ClipOutliersOp(BaseOperation):
    operation: Literal["clip_outliers"] = "clip_outliers"
    column: Optional[str] = None
    method: Literal["iqr", "zscore", "percentile"] = "iqr"
    k: float = 1.5
    action: Literal["clip", "drop"] = "clip"
    lower_quantile: float = 0.01
    upper_quantile: float = 0.99

    def to_plan_dict(self) -> dict:
        if self.action == "drop" and self.method == "iqr":
            canonical_op = "drop_iqr_rows"
        elif self.method == "percentile":
            canonical_op = "clip_percentile"
        else:
            canonical_op = "clip_iqr"
        return {
            "column": self.column,
            "operation": canonical_op,
            "parameters": {
                "k": self.k,
                "lower_quantile": self.lower_quantile,
                "upper_quantile": self.upper_quantile,
                "action": self.action,
                "method": self.method
            },
            "message": f"Handle outliers in '{self.column}' using {self.method} ({self.action})."
        }


class LogTransformOp(BaseOperation):
    operation: Literal["log_transform"] = "log_transform"
    column: Optional[str] = None
    offset: float = 1.0

    def to_plan_dict(self) -> dict:
        return {
            "column": self.column,
            "operation": "log_transform",
            "parameters": {"offset": self.offset},
            "message": f"Apply log(1+x) transformation to '{self.column}' (preserving negatives as NaN)."
        }


class ConvertTypeOp(BaseOperation):
    operation: Literal["convert_type"] = "convert_type"
    column: Optional[str] = None
    target_type: Literal["int", "float", "string", "boolean", "datetime"]

    def to_plan_dict(self) -> dict:
        return {
            "column": self.column,
            "operation": "convert_datatype",
            "parameters": {"dtype": self.target_type},
            "message": f"Convert datatype of '{self.column}' to '{self.target_type}'."
        }


class RoundNumericOp(BaseOperation):
    operation: Literal["round_numeric"] = "round_numeric"
    column: Optional[str] = None
    decimals: int = 0

    def to_plan_dict(self) -> dict:
        return {
            "column": self.column,
            "operation": "round_values",
            "parameters": {"decimals": self.decimals},
            "message": f"Round '{self.column}' to {self.decimals} decimal places."
        }


class RenameColumnOp(BaseOperation):
    operation: Literal["rename_column"] = "rename_column"
    column: Optional[str] = None
    new_name: str

    def to_plan_dict(self) -> dict:
        return {
            "column": self.column,
            "operation": "rename_column",
            "parameters": {"new_name": self.new_name},
            "message": f"Rename '{self.column}' to '{self.new_name}'."
        }


class StripWhitespaceOp(BaseOperation):
    operation: Literal["strip_whitespace"] = "strip_whitespace"
    column: Optional[str] = None

    def to_plan_dict(self) -> dict:
        return {
            "column": self.column,
            "operation": "strip_whitespace",
            "parameters": {},
            "message": f"Strip leading and trailing whitespace from '{self.column}'."
        }


class CaseTransformOp(BaseOperation):
    operation: Literal["case_transform"] = "case_transform"
    column: Optional[str] = None
    case: Literal["lower", "upper", "title"] = "lower"

    def to_plan_dict(self) -> dict:
        op_name = {"lower": "lowercase", "upper": "uppercase", "title": "titlecase"}.get(self.case, "lowercase")
        return {
            "column": self.column,
            "operation": op_name,
            "parameters": {},
            "message": f"Transform text in '{self.column}' to {self.case} case."
        }


# Discriminated Union of all supported operations
CleaningOperation = Annotated[
    Union[
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
    ],
    Field(discriminator="operation")
]


class ColumnRecommendation(BaseModel):
    """Schema for individual column recommendation returned by AI or UI."""
    model_config = ConfigDict(extra="ignore")
    column: str
    action: Literal["keep", "drop", "transform"]
    reason: str
    transformation: Optional[str] = None
    operations: Optional[List[CleaningOperation]] = None


class CleaningPlanModel(BaseModel):
    """Top-level container for a full dataset cleaning plan."""
    model_config = ConfigDict(extra="ignore")
    recommendations: Optional[List[ColumnRecommendation]] = None
    operations: Optional[List[CleaningOperation]] = None


def parse_typed_operation(op_data: dict, default_column: Optional[str] = None) -> Optional[CleaningOperation]:
    """Parse and validate a dictionary into a typed Pydantic CleaningOperation."""
    if not isinstance(op_data, dict):
        return None
    op_name = op_data.get("operation")
    if not op_name:
        return None

    type_map = {
        "drop_column": DropColumnOp,
        "keep_column": KeepColumnOp,
        "replace_value": ReplaceValueOp,
        "impute": ImputeOp,
        "normalize": NormalizeOp,
        "encode": EncodeOp,
        "parse_date": ParseDateOp,
        "drop_duplicates": DropDuplicatesOp,
        "clip_outliers": ClipOutliersOp,
        "log_transform": LogTransformOp,
        "convert_type": ConvertTypeOp,
        "convert_datatype": ConvertTypeOp,
        "round_numeric": RoundNumericOp,
        "round_values": RoundNumericOp,
        "rename_column": RenameColumnOp,
        "strip_whitespace": StripWhitespaceOp,
        "case_transform": CaseTransformOp,
    }

    cls = type_map.get(op_name)
    if not cls:
        return None

    # Merge inner parameters into flat kwargs if needed
    kwargs = dict(op_data)
    if "parameters" in kwargs and isinstance(kwargs["parameters"], dict):
        for k, v in kwargs["parameters"].items():
            if k not in kwargs:
                kwargs[k] = v

    if ("column" not in kwargs or not kwargs.get("column")) and default_column:
        kwargs["column"] = default_column

    # Normalize some keys
    if "dtype" in kwargs and "target_type" not in kwargs:
        kwargs["target_type"] = kwargs["dtype"]
    if "decimals" in kwargs and cls is RoundNumericOp:
        kwargs["decimals"] = int(kwargs["decimals"])

    try:
        return cls.model_validate(kwargs)
    except Exception:
        return None


def validate_operation_against_dataframe(op: BaseOperation, df: pd.DataFrame) -> tuple[bool, Optional[str]]:
    """
    Validates column names, operations, and parameters against the real DataFrame before executing.
    Returns: (is_valid, error_message)
    """
    col = getattr(op, "column", None)

    # 1. Dataset-scope operations (drop_duplicates with None column or subset)
    if isinstance(op, DropDuplicatesOp):
        if op.subset:
            missing_cols = [c for c in op.subset if c not in df.columns]
            if missing_cols:
                return False, f"Subset columns {missing_cols} for drop_duplicates do not exist in DataFrame."
        return True, None

    # 2. Operations requiring an existing column
    if col is not None:
        if col not in df.columns:
            # Case-insensitive match check
            ci_matches = [c for c in df.columns if c.lower() == col.lower()]
            if ci_matches:
                op.column = ci_matches[0]
                col = ci_matches[0]
            else:
                return False, f"Target column '{col}' does not exist in DataFrame."

    # 3. Type-constraint validation
    if col in df.columns:
        is_num = pd.api.types.is_numeric_dtype(df[col])
        is_txt = pd.api.types.is_string_dtype(df[col]) or df[col].dtype == object

        if isinstance(op, (NormalizeOp, ClipOutliersOp, LogTransformOp, RoundNumericOp)):
            if not is_num:
                # Check if it can be coerced to numeric safely
                try:
                    test = pd.to_numeric(df[col].dropna(), errors='raise')
                except Exception:
                    return False, f"Operation '{op.operation}' requires a numeric column, but '{col}' has dtype '{df[col].dtype}'."

        if isinstance(op, ImputeOp) and op.method in ("mean", "median"):
            if not is_num:
                try:
                    test = pd.to_numeric(df[col].dropna(), errors='raise')
                except Exception:
                    return False, f"Imputation method '{op.method}' requires a numeric column, but '{col}' has dtype '{df[col].dtype}'."

        if isinstance(op, (StripWhitespaceOp, CaseTransformOp)) and not is_txt:
            return False, f"Text operation '{op.operation}' requires a string/text column, but '{col}' has dtype '{df[col].dtype}'."

    return True, None
