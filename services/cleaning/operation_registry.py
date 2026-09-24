"""
operation_registry.py — Central Registry of All Supported Cleaning Operations
==============================================================================
Each entry defines:
    name            — canonical operation identifier
    aliases         — keyword phrases that trigger this operation
    scope           — 'column' | 'dataset'
    changes_rows    — True if rows may be added/removed
    changes_columns — True if columns may be added/removed
    changes_values  — True if cell values change
    dtype_constraint — 'numeric' | 'text' | 'datetime' | 'any'
    required_params — list of required parameter keys
    description     — human-readable summary
"""

import re

OPERATIONS = {

    # ── STRUCTURAL ────────────────────────────────────────────────────────────
    "drop_column": {
        "aliases": ["drop", "remove", "delete", "eliminate", "omit", "remove column", "delete column", "drop column", "eliminate column"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Remove a column from the dataset."
    },

    "rename_column": {
        "aliases": ["rename to", "rename column to"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "any", "required_params": ["new_name"],
        "description": "Rename a column."
    },
    "move_column_front": {
        "aliases": ["move to front", "reorder first", "move first"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Move column to the first position."
    },
    "move_column_end": {
        "aliases": ["move to end", "reorder last", "move last"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Move column to the last position."
    },
    "drop_constant_column": {
        "aliases": ["drop constant", "drop low variance", "constant column", "zero variance"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Drop a column if it has only one unique value."
    },
    "keep_column": {
        "aliases": ["keep unchanged", "keep as is", "keep this column", "retain", "no change"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Explicitly mark column as unchanged. No transformation applied."
    },
    "keep_only_columns": {
        "aliases": ["keep only", "keep only these columns", "drop all except", "retain only"],
        "scope": "dataset",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "any", "required_params": ["columns"],
        "description": "Remove every column except the specified list."
    },

    # ── MISSING VALUES ────────────────────────────────────────────────────────
    "normalize_missing_placeholders": {
        "aliases": ["normalize missing", "clean null placeholders", "placeholder", "handle placeholders",
                    "fake nulls", "normalize nulls", "fake null"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Convert fake null strings (N/A, None, -, ?, etc.) to real NaN."
    },
    "handle_infinity": {
        "aliases": ["handle inf", "replace inf", "remove inf", "infinity"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Replace inf and -inf with NaN."
    },
    "impute_mean": {
        "aliases": ["fill with mean", "impute mean", "fill mean", "replace missing with mean",
                    "fill missing with mean", "fill null with mean"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Fill missing values with column mean."
    },
    "impute_median": {
        "aliases": ["fill with median", "impute median", "fill median", "replace missing with median",
                    "fill missing with median", "fill null with median"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Fill missing values with column median."
    },
    "impute_mode": {
        "aliases": ["fill with mode", "impute mode", "fill mode", "replace missing with mode",
                    "fill missing with mode", "fill null with mode"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Fill missing values with column mode."
    },
    "impute_zero": {
        "aliases": ["fill 0", "fill zero", "impute 0", "fill missing with 0", "replace missing with 0",
                    "fill null with 0", "fill with zero"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Fill missing values with zero."
    },
    "impute_custom": {
        "aliases": ["fill with", "replace missing with", "fill null with", "fill na with",
                    "replace nan with", "fill missing", "fill empty with"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": ["fill_value"],
        "description": "Fill missing values with a custom value."
    },
    "drop_null_rows": {
        "aliases": ["drop null rows", "remove null rows", "drop rows with null",
                    "remove rows with null", "drop rows with missing", "remove missing rows",
                    "drop na", "remove na", "drop rows containing null"],
        "scope": "dataset",
        "changes_rows": True, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Remove all rows that contain any null/NaN value."
    },
    "drop_null_rows_column": {
        "aliases": ["remove rows where null", "drop rows where null", "drop rows where missing",
                    "remove rows where missing", "remove rows where is null"],
        "scope": "column",
        "changes_rows": True, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Remove rows where this specific column has a null/NaN value."
    },

    # ── DUPLICATES ─────────────────────────────────────────────────────────────
    "drop_duplicates_full": {
        "aliases": ["drop full duplicates", "remove whole duplicates", "deduplicate dataset",
                    "drop all duplicates", "remove duplicate rows", "drop duplicate rows",
                    "remove duplicates"],
        "scope": "dataset",
        "changes_rows": True, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Remove fully duplicate rows."
    },
    "drop_duplicates_by_columns": {
        "aliases": ["remove duplicates based on", "deduplicate by", "drop duplicates by",
                    "remove duplicate", "keep first record", "keep last record",
                    "keep first occurrence", "keep last occurrence"],
        "scope": "column",
        "changes_rows": True, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": ["keep"],
        "description": "Remove duplicate rows using this column as the subset key."
    },

    # ── TEXT CLEANING ──────────────────────────────────────────────────────────
    "uppercase": {
        "aliases": ["upper", "uppercase", "to upper", "convert to upper", "make uppercase"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": [],
        "description": "Convert text to UPPERCASE."
    },
    "lowercase": {
        "aliases": ["lower", "lowercase", "to lower", "convert to lower", "make lowercase"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": [],
        "description": "Convert text to lowercase."
    },
    "titlecase": {
        "aliases": ["title", "titlecase", "capitalize", "title case", "proper case"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": [],
        "description": "Convert text to Title Case."
    },
    "strip_whitespace": {
        "aliases": ["strip", "trim", "whitespace", "trim whitespace", "remove whitespace",
                    "strip spaces", "trim spaces"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": [],
        "description": "Remove leading and trailing whitespace."
    },
    "normalize_blank": {
        "aliases": ["normalize blank", "blank to null", "empty to null", "blank to nan",
                    "convert blank to null", "blank normalization"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Convert blank/whitespace-only strings to NaN."
    },
    "remove_punctuation": {
        "aliases": ["strip punctuation", "remove punctuation", "punctuation", "special chars",
                    "clean special", "strip special characters"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": [],
        "description": "Remove punctuation characters."
    },
    "remove_html": {
        "aliases": ["strip html", "remove html", "clean html", "html tags", "remove html tags"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": [],
        "description": "Strip HTML tags."
    },
    "remove_stopwords": {
        "aliases": ["remove stopwords", "strip stopwords", "stopwords", "filter stopwords"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": [],
        "description": "Remove common English stopwords."
    },
    "string_length": {
        "aliases": ["string length", "str len", "length feature", "text length", "char count"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "text", "required_params": [],
        "description": "Create a new column with the character length of each string."
    },
    "extract_digits": {
        "aliases": ["extract digits", "extract numbers from"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "text", "required_params": [],
        "description": "Extract numeric digits into a new column."
    },
    "extract_email": {
        "aliases": ["extract email", "parse email"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "text", "required_params": [],
        "description": "Extract email addresses into a new column."
    },
    "extract_phone": {
        "aliases": ["extract phone", "parse phone", "extract phone number"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "text", "required_params": [],
        "description": "Extract phone numbers into a new column."
    },
    "split_column": {
        "aliases": ["split by", "split column by", "split on"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "text", "required_params": ["separator"],
        "description": "Split column into multiple columns by delimiter."
    },
    "concat_column": {
        "aliases": ["concat with", "concatenate with", "combine with", "merge with column"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": ["other_col"],
        "description": "Concatenate this column with another column."
    },

    # ── VALUE REPLACEMENT ──────────────────────────────────────────────────────
    "replace_value_exact": {
        "aliases": ["replace", "replace with", "change value", "map value", "where", "substitute"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": ["mapping"],
        "description": "Replace exact cell values with new values."
    },
    "replace_value_substring": {
        "aliases": ["replace substring", "replace text", "replace wherever", "wherever it appears"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": ["old", "new"],
        "description": "Replace a substring within cell values."
    },
    "replace_value_regex": {
        "aliases": ["replace regex", "regex replace", "remove non-numeric", "remove non-alpha",
                    "remove all non"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": ["pattern", "replacement"],
        "description": "Replace using a regular expression pattern."
    },

    # ── ENCODING ───────────────────────────────────────────────────────────────
    "one_hot_encode": {
        "aliases": ["one-hot", "onehot", "dummy", "dummies", "one hot", "get dummies", "encode", "encode categorical", "categorical encoding", "nominal encode"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "text", "required_params": [],
        "description": "One-hot encode a nominal categorical column (default for nominal categoricals)."
    },
    "ordinal_encode": {
        "aliases": ["ordinal", "ordinal encode", "ordinal order"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Ordinal encode categorical values."
    },
    "frequency_encode": {
        "aliases": ["frequency encode", "freq encode", "occurrence count", "frequency mapping"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Encode values by their frequency/proportion in the column."
    },
    "label_encode": {
        "aliases": ["label encode", "label encoding", "factorize"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Label encode a categorical column to integer codes."
    },
    "normalize_boolean": {
        "aliases": ["normalize bool", "boolean normalize", "yes/no", "y/n", "true/false to 0/1",
                    "convert boolean", "bool to int"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Normalize boolean-like values (yes/no, true/false) to 1/0."
    },

    # ── NUMERIC ────────────────────────────────────────────────────────────────
    "convert_percentage": {
        "aliases": ["percent", "percentage", "parse percent", "convert percent"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Parse percentage strings (e.g. '75%') to decimal (0.75)."
    },
    "parse_accounting_currency": {
        "aliases": ["accounting", "parentheses negative", "accounting format"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Parse accounting-format currency (parentheses = negative)."
    },
    "remove_currency_symbol": {
        "aliases": ["currency", "symbol", "price", "dollar", "strip symbols", "remove currency",
                    "clean currency", "strip currency"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Remove currency symbols and convert to numeric."
    },
    "normalize_minmax": {
        "aliases": ["normalize", "min-max", "minmax", "scale", "min max scale"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Apply Min-Max normalization to scale values between 0 and 1."
    },
    "standardize_zscore": {
        "aliases": ["standardize", "z-score", "zscore", "standard score"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Apply Z-score standardization (mean=0, std=1)."
    },
    "log_transform": {
        "aliases": ["log transform", "log1p", "logarithm", "log scale"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Apply log(1+x) transformation."
    },
    "round_values": {
        "aliases": ["round to", "round to nearest", "round values", "round to integer"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Round numeric values to specified decimal places."
    },
    "convert_datatype": {
        "aliases": ["convert to", "cast to", "change type to", "change dtype to",
                    "as integer", "as int", "as float", "as string", "as str",
                    "as bool", "as boolean", "as category", "as datetime",
                    "to integer", "to int", "to float", "to string", "to str",
                    "to bool", "to boolean", "to category", "to datetime"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": ["dtype"],
        "description": "Convert column datatype (int, float, str, bool, category, datetime)."
    },
    "derived_math": {
        "aliases": ["multiply by", "add by", "subtract by", "divide by"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "numeric", "required_params": ["operation", "target"],
        "description": "Create a derived column using a math operation with another column."
    },

    # ── UNIT CONVERSIONS ───────────────────────────────────────────────────────
    "convert_unit": {
        "aliases": [
            "kg to lb", "lb to kg", "lbs to kg",
            "km to mi", "mi to km",
            "c to f", "f to c",
            "m to ft", "ft to m",
            "g to kg", "kg to g",
            "cm to inch", "inch to cm", "cm to in", "in to cm",
            "l to gallon", "gallon to l", "liter to gallon", "gallon to liter",
            "ml to l", "l to ml", "ml to liter", "liter to ml",
        ],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": ["from_unit", "to_unit"],
        "description": "Convert values from one unit to another."
    },

    # ── DATETIME ───────────────────────────────────────────────────────────────
    "extract_year": {
        "aliases": ["extract year", "year from", "get year"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Extract year from a datetime column into a new column."
    },
    "extract_month": {
        "aliases": ["extract month", "month from", "get month"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Extract month from a datetime column."
    },
    "extract_day": {
        "aliases": ["extract day", "day from", "get day"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Extract day-of-month from a datetime column."
    },
    "extract_weekday": {
        "aliases": ["extract weekday", "weekday from", "day name", "get weekday"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Extract day-of-week name from a datetime column."
    },
    "extract_quarter": {
        "aliases": ["extract quarter", "quarter from", "get quarter"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Extract quarter (1-4) from a datetime column."
    },
    "extract_hour": {
        "aliases": ["extract hour", "hour from", "get hour"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Extract hour from a datetime column."
    },
    "extract_minute": {
        "aliases": ["extract minute", "minute from", "get minute"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Extract minute from a datetime column."
    },
    "extract_weekend": {
        "aliases": ["is weekend", "weekend flag", "weekend detection", "extract weekend"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Create a boolean column indicating if the date is a weekend."
    },
    "days_since": {
        "aliases": ["days since", "days ago", "days from today"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": [],
        "description": "Calculate days elapsed since each date until today."
    },
    "date_difference": {
        "aliases": ["date difference", "date diff", "diff from column"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "datetime", "required_params": ["ref_col"],
        "description": "Calculate the difference in days between two date columns."
    },
    "standardize_datetime": {
        "aliases": ["standardize datetime", "standardize date", "normalize date",
                    "parse date", "format date", "convert date"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "any", "required_params": [],
        "description": "Standardize date strings to ISO 8601 format (YYYY-MM-DD HH:MM:SS)."
    },

    # ── OUTLIERS ───────────────────────────────────────────────────────────────
    "clip_iqr": {
        "aliases": ["iqr clip", "clip iqr", "iqr outlier clip", "clip outliers iqr"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Clip values outside the IQR fence (Q1-1.5×IQR, Q3+1.5×IQR)."
    },
    "drop_iqr_rows": {
        "aliases": ["iqr drop", "drop iqr outlier rows", "remove iqr outlier rows",
                    "iqr remove", "drop outlier rows iqr"],
        "scope": "column",
        "changes_rows": True, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Remove rows where the column value is an IQR outlier."
    },
    "clip_percentile": {
        "aliases": ["percentile clip", "clip percentile", "clip 1st 99th", "trim outliers",
                    "percentile outlier"],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Clip values outside the 1st–99th percentile range."
    },

    # ── ROWS ───────────────────────────────────────────────────────────────────
    "filter_rows": {
        "aliases": ["filter rows where", "keep rows where", "select rows where"],
        "scope": "dataset",
        "changes_rows": True, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": ["col", "op", "val"],
        "description": "Keep only rows matching a filter condition."
    },
    "remove_rows": {
        "aliases": ["remove rows where", "delete rows where", "drop rows where"],
        "scope": "dataset",
        "changes_rows": True, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": ["col", "op", "val"],
        "description": "Remove rows matching a filter condition."
    },
    "explode_column": {
        "aliases": ["explode", "split cells", "explode by"],
        "scope": "column",
        "changes_rows": True, "changes_columns": False, "changes_values": True,
        "dtype_constraint": "text", "required_params": ["separator"],
        "description": "Split multi-value delimited cells and explode into multiple rows."
    },

    # ── STRUCTURAL / BINNING ──────────────────────────────────────────────────
    "bin_column": {
        "aliases": ["bin", "bucket", "qcut", "cut", "bin into", "bucket into"],
        "scope": "column",
        "changes_rows": False, "changes_columns": True, "changes_values": False,
        "dtype_constraint": "numeric", "required_params": [],
        "description": "Bin numeric values into quantile or equal-width buckets."
    },

    # ── UNSUPPORTED (explicit sentinel) ───────────────────────────────────────
    "unsupported": {
        "aliases": [],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Placeholder for unrecognized operations. No data is modified."
    },
    "ambiguous_instruction": {
        "aliases": [],
        "scope": "column",
        "changes_rows": False, "changes_columns": False, "changes_values": False,
        "dtype_constraint": "any", "required_params": [],
        "description": "Placeholder for ambiguous instructions. No data is modified."
    },
}

# ID-like column patterns (protected from broad normalizations)
ID_COLUMN_PATTERNS = [
    r"^id$", r".*_id$", r"^id_.*", r".*_key$", r"^key$",
    r".*_code$", r"^uuid$", r"^guid$", r".*_num$", r".*_number$",
    r"^email$", r"^email_id$",
]

# Supported datatype conversion targets
DTYPE_CONVERSION_TARGETS = {
    "int":       ["int", "integer", "int64", "int32"],
    "float":     ["float", "float64", "float32", "double", "decimal", "numeric"],
    "str":       ["str", "string", "text", "varchar", "object"],
    "bool":      ["bool", "boolean"],
    "category":  ["category", "categorical", "cat"],
    "datetime":  ["datetime", "date", "timestamp", "time"],
}

# Unit conversion factor map: (from_unit, to_unit) → lambda
UNIT_CONVERSIONS = {
    ("kg", "lb"):      lambda x: x * 2.20462,
    ("lb", "kg"):      lambda x: x / 2.20462,
    ("lbs", "kg"):     lambda x: x / 2.20462,
    ("km", "mi"):      lambda x: x * 0.621371,
    ("mi", "km"):      lambda x: x / 0.621371,
    ("c", "f"):        lambda x: x * 9 / 5 + 32,
    ("f", "c"):        lambda x: (x - 32) * 5 / 9,
    ("m", "ft"):       lambda x: x * 3.28084,
    ("ft", "m"):       lambda x: x / 3.28084,
    ("g", "kg"):       lambda x: x / 1000.0,
    ("kg", "g"):       lambda x: x * 1000.0,
    ("cm", "inch"):    lambda x: x / 2.54,
    ("cm", "in"):      lambda x: x / 2.54,
    ("inch", "cm"):    lambda x: x * 2.54,
    ("in", "cm"):      lambda x: x * 2.54,
    ("l", "gallon"):   lambda x: x * 0.264172,
    ("gallon", "l"):   lambda x: x / 0.264172,
    ("liter", "gallon"): lambda x: x * 0.264172,
    ("gallon", "liter"): lambda x: x / 0.264172,
    ("ml", "l"):       lambda x: x / 1000.0,
    ("l", "ml"):       lambda x: x * 1000.0,
    ("ml", "liter"):   lambda x: x / 1000.0,
    ("liter", "ml"):   lambda x: x * 1000.0,
}


def get_operation(name: str) -> dict:
    """Return operation definition by canonical name, or None."""
    return OPERATIONS.get(name)


def find_operation_by_keyword(keyword: str) -> list:
    """
    Return a list of (op_name, op_def) matching aliases using word boundaries.
    Prevents false-positive substring collisions (e.g. '0', 'log', 'int' inside other words).
    Sorted by alias specificity (longer alias = more specific = higher priority).
    """
    keyword = keyword.lower().strip()
    if not keyword:
        return []
    matches = []
    for op_name, op_def in OPERATIONS.items():
        if op_name in ("unsupported", "ambiguous_instruction"):
            continue
        for alias in op_def["aliases"]:
            alias_lower = alias.lower().strip()
            if alias_lower == keyword:
                matches.append((op_name, op_def, len(alias_lower) + 100))
            elif len(alias_lower) >= 3 and re.search(rf'(?:\b|_){re.escape(alias_lower)}(?:\b|_)', keyword):
                matches.append((op_name, op_def, len(alias_lower)))
    # Sort by alias length descending (most specific first)
    matches.sort(key=lambda x: x[2], reverse=True)
    seen = set()
    unique_matches = []
    for m in matches:
        if m[0] not in seen:
            seen.add(m[0])
            unique_matches.append((m[0], m[1]))
    return unique_matches


def is_likely_id_column(col_name: str) -> bool:
    """Return True if the column name looks like an identifier column."""
    import re
    col_lower = col_name.lower()
    for pattern in ID_COLUMN_PATTERNS:
        if re.match(pattern, col_lower):
            return True
    return False


def resolve_dtype_target(text: str) -> str | None:
    """
    Given a text fragment, return the canonical dtype key or None.
    E.g. "integer" → "int", "category" → "category"
    """
    text_lower = text.lower().strip()
    for canonical, aliases in DTYPE_CONVERSION_TARGETS.items():
        if text_lower in aliases:
            return canonical
    return None
