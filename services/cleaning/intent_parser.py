"""
intent_parser.py — Natural Language → Structured Cleaning Plan
===============================================================
Converts a raw user transformation string into an ordered list of
structured operation dicts that can be validated and executed safely.

Architecture:
    raw_trans_string
        → polish_prompt()
        → split into steps (chained operations)
        → for each step: match_operation() + extract_parameters()
        → return list of operation dicts

Each operation dict:
{
    "column":     str,
    "operation":  str,   # canonical op name from operation_registry
    "parameters": dict,
    "order":      int,
    "raw_step":   str,   # original text for debugging
    "message":    str,   # human-readable description or error message
}

Key safety guarantees:
  - Unrecognized operations → {"operation": "unsupported"}, NO data modified
  - Ambiguous column references → {"operation": "ambiguous_column"}, NO data modified
  - "keep" instructions → {"operation": "keep_column"}, NO data modified
  - "keep only" instructions → {"operation": "keep_only_columns"}, dataset-scope
  - No eval() or exec() usage
"""

import re
import difflib
import logging
from services.cleaning.operation_registry import (
    OPERATIONS,
    DTYPE_CONVERSION_TARGETS,
    UNIT_CONVERSIONS,
    find_operation_by_keyword,
    is_likely_id_column,
    resolve_dtype_target,
)


# ── Typo / slang correction map ───────────────────────────────────────────────
_TYPO_MAP = {
    r'\btranform\b': 'transform',
    r'\bperfrom\b': 'perform',
    r'\btranformation\b': 'transformation',
    r'\bcolum\b': 'column',
    r'\bcolums\b': 'columns',
    r'\breove\b': 'remove',
    r'\bdelte\b': 'delete',
    r'\bupcase\b': 'uppercase',
    r'\blowcase\b': 'lowercase',
    r'\bnul\b': 'null',
    r'\bdups\b': 'duplicates',
    r'\bduplicats\b': 'duplicates',
    r'\bintger\b': 'integer',
    r'\bintegr\b': 'integer',
    r'\bfloat\b': 'float',
    r'\bstandardise\b': 'standardize',
    r'\bnormalise\b': 'normalize',
    r'\blabelling\b': 'label',
}

# ── Step splitter ─────────────────────────────────────────────────────────────
_STEP_SPLIT_PATTERN = re.compile(
    r'\s*(?:,\s*then\s+|\s+then\s+|\s*;\s*|\s*&&\s*)\s*',
    flags=re.IGNORECASE
)

# Separators to recognize keep-only instructions
_KEEP_ONLY_PATTERN = re.compile(
    r'keep\s+only\s+(.*)', flags=re.IGNORECASE
)

# "keep X unchanged" pattern (not "keep only")
_KEEP_COLUMN_PATTERN = re.compile(
    r'\b(?:keep|retain|preserve|leave)\b(?!\s+only)', flags=re.IGNORECASE
)


def _polish_prompt(raw: str) -> str:
    """Apply typo corrections and basic normalization to a raw prompt string."""
    if not raw or not isinstance(raw, str):
        return ""
    polished = raw.strip()
    for pattern, correction in _TYPO_MAP.items():
        polished = re.sub(pattern, correction, polished, flags=re.IGNORECASE)
    return polished


def _find_column_in_text(text: str, df_columns: list) -> tuple:
    """
    Find which dataframe column is referenced in the text.
    Priority:
        1. Exact match (case-sensitive)
        2. Case-insensitive match
        3. Space↔underscore-normalized match
        4. Fuzzy match (ratio >= 0.78)

    Returns:
        (matched_col_name, "exact"|"ci"|"normalized"|"fuzzy"|"ambiguous"|"none", candidates)
    """
    if not text or not df_columns:
        return (None, "none", [])

    text_lower = text.lower()
    text_clean = re.sub(r'[^a-z0-9 ]', ' ', text_lower)

    # 1. Exact
    for col in df_columns:
        if col in text:
            return (col, "exact", [col])

    # 2. Case-insensitive
    ci_matches = [col for col in df_columns if col.lower() in text_lower]
    if len(ci_matches) == 1:
        return (ci_matches[0], "ci", ci_matches)
    if len(ci_matches) > 1:
        # Multiple case-insensitive matches: sort by length descending (most specific)
        ci_matches.sort(key=len, reverse=True)
        # If the longest match dominates, use it
        if len(ci_matches[0]) > len(ci_matches[1]) + 2:
            return (ci_matches[0], "ci", ci_matches)
        return (None, "ambiguous", ci_matches)

    # 3. Space/underscore normalized
    norm_matches = []
    for col in df_columns:
        col_norm = re.sub(r'[^a-z0-9]', ' ', col.lower()).strip()
        if col_norm in text_clean or text_clean.strip() in col_norm:
            norm_matches.append(col)
    if len(norm_matches) == 1:
        return (norm_matches[0], "normalized", norm_matches)
    if len(norm_matches) > 1:
        return (None, "ambiguous", norm_matches)

    # 4. Fuzzy matching
    text_words = [w for w in re.sub(r'[^a-z0-9]', ' ', text_lower).split() if len(w) > 2]
    fuzzy_scores = {}
    for col in df_columns:
        col_clean = re.sub(r'[^a-z0-9]', '', col.lower())
        best_ratio = 0.0
        for word in text_words:
            r = difflib.SequenceMatcher(None, col_clean, word).ratio()
            if r > best_ratio:
                best_ratio = r
        fuzzy_scores[col] = best_ratio

    candidates = [(col, score) for col, score in fuzzy_scores.items() if score >= 0.78]
    candidates.sort(key=lambda x: x[1], reverse=True)

    if not candidates:
        return (None, "none", [])
    if len(candidates) == 1:
        return (candidates[0][0], "fuzzy", [candidates[0][0]])

    # Multiple fuzzy candidates — check if top one is significantly better
    top_score = candidates[0][1]
    close_candidates = [c for c, s in candidates if s >= top_score - 0.05]
    if len(close_candidates) == 1:
        return (close_candidates[0], "fuzzy", close_candidates)

    # Ambiguous fuzzy match
    return (None, "ambiguous", [c for c, _ in candidates[:5]])


def _extract_value_mapping(step_str: str, col_name: str) -> dict:
    """
    Extract value replacement mappings from human language step strings.
    Handles:
        replace '0' with 'No' and '1' with 'Yes'
        0 -> No, 1 -> Yes
        0 to No, 1 to Yes
        change 0 to No and 1 to Yes
        0 = No, 1 = Yes
        make 0 No and 1 Yes
        where 0 set No
        replace Tesla with Tesla Motors
    """
    col_lower = (col_name or "").lower()
    stop_words = {'where', 'there', 'is', 'replace', 'it', 'with', 'to', 'in',
                  'and', 'column', 'columns', 'transform', 'convert', 'change',
                  'make', 'turn', 'set', 'into', col_lower, 'the', 'value',
                  'values', 'each', 'all', 'data', 'dataset'}

    mapping = {}

    # Strip out column name prefix if present at start (e.g. "CardiovascularDisease transform 0 to No")
    clean_step = step_str
    if col_name and clean_step.lower().startswith(col_lower):
        clean_step = clean_step[len(col_name):].strip()

    # Strip out leading verb keywords like transform, convert, change, replace, set, make
    clean_step = re.sub(r'^(?:transform|convert|change|replace|set|make)\s+', '', clean_step, flags=re.IGNORECASE).strip()
    # Strip column noise words if prefixing value (e.g. "column 'others'" -> "'others'")
    clean_step = re.sub(r'\b(?:column|col|columns|feature|attribute|values?)\s+', '', clean_step, flags=re.IGNORECASE).strip()

    # Pattern 1: Explicit transform/replace/change/convert 'X' with/to/into 'Y'
    p1 = re.findall(
        r"""(?:transform|replace|change|convert|turn|make|set)?\s*['"]?([^'"]+?)['"]?\s+(?:with|to|into|=)\s+['"]?([^'"]+?)['"]?(?:\s+and\s+|$|,)""",
        clean_step, re.IGNORECASE
    )
    for old_v, new_v in p1:
        old_v, new_v = old_v.strip(), new_v.strip()
        if old_v.lower() not in stop_words and new_v.lower() not in stop_words:
            mapping[old_v] = new_v

    if mapping:
        return mapping

    # Pattern 2: Arrow or Equals pairs: X -> Y, X => Y, X = Y
    p2 = re.findall(
        r"""['"]?([^'"]+?)['"]?\s*(?:->|=>|=)\s*['"]?([^'"]+?)['"]?(?:\s+and\s+|$|,)""",
        clean_step, re.IGNORECASE
    )
    for old_v, new_v in p2:
        old_v, new_v = old_v.strip(), new_v.strip()
        if old_v.lower() not in stop_words and new_v.lower() not in stop_words:
            mapping[old_v] = new_v

    if mapping:
        return mapping

    # Pattern 3: Shorthand "X to Y" pairs: 0 to No, 1 to Yes
    p3 = re.findall(
        r"""\b([a-zA-Z0-9_.\-\$]+)\s+(?:to|into)\s+([a-zA-Z0-9_.\-\$\s]+?)(?:\s+and\s+|$|,)""",
        clean_step, re.IGNORECASE
    )
    for old_v, new_v in p3:
        old_v, new_v = old_v.strip(), new_v.strip()
        if old_v.lower() not in stop_words and new_v.lower() not in stop_words:
            mapping[old_v] = new_v

    return mapping


def _detect_operation(step_lower: str) -> str:
    """
    Detect the canonical operation name from a single cleaned step string.
    Returns the canonical op name, "unsupported", or "ambiguous_instruction".
    Priority: more-specific aliases beat shorter/generic ones.
    """
    # ── Special: keep-only (must be checked before generic keep) ──────────────
    if re.search(r'\bkeep\s+only\b', step_lower, re.IGNORECASE):
        return "keep_only_columns"

    # ── Special: keep first / keep last for duplicate removal ─────────────────
    if re.search(r'\bkeep\s+(?:first|last|none)\b', step_lower, re.IGNORECASE):
        return "drop_duplicates_by_columns"

    # ── Special: keep column unchanged ────────────────────────────────────────
    if re.search(r'\b(?:keep|retain|preserve|leave)\b', step_lower, re.IGNORECASE):
        if not re.search(r'\bkeep\s+(?:only|first|last)\b', step_lower, re.IGNORECASE):
            return "keep_column"

    # ── Special: rename column ────────────────────────────────────────────────
    if re.search(r'\brename(?:\s+column)?\s+to\b', step_lower, re.IGNORECASE):
        return "rename_column"

    # ── Special: move column position ──────────────────────────────────────────
    if re.search(r'\bmove\s+to\s+front\b|\breorder\s+first\b|\bmove\s+first\b', step_lower, re.IGNORECASE):
        return "move_column_front"
    if re.search(r'\bmove\s+to\s+end\b|\breorder\s+last\b|\bmove\s+last\b', step_lower, re.IGNORECASE):
        return "move_column_end"

    # ── Null row removal (column-specific vs global) ──────────────────────────
    if re.search(r'\b(?:remove|drop|delete)\s+rows\s+where\b.*\b(?:null|nan|missing|empty|blank)\b',
                 step_lower, re.IGNORECASE):
        return "drop_null_rows_column"
    if re.search(r'\b(?:null|nan|missing)\b.*\brows?\b', step_lower, re.IGNORECASE):
        if re.search(r'\b(?:drop|remove|delete)\b', step_lower, re.IGNORECASE):
            return "drop_null_rows"

    # ── Row filter vs row remove ───────────────────────────────────────────────
    if re.search(r'\b(?:remove|delete|drop)\s+rows?\s+where\b', step_lower, re.IGNORECASE):
        return "remove_rows"
    if re.search(r'\b(?:keep|filter)\s+rows?\s+where\b', step_lower, re.IGNORECASE):
        return "filter_rows"

    # ── Datatype conversion ────────────────────────────────────────────────────
    dt_match = re.search(
        r'\b(?:convert|cast|change\s+type|change\s+dtype|type|as|to|make|turn\s+into|set\s+type)?\s*'
        r'\b(int(?:eger)?|number|numeric|float|decimal|double|str(?:ing)?|text|bool(?:ean)?|flag|categor(?:y|ical)|datetime|date|timestamp|object)\b',
        step_lower, re.IGNORECASE
    )
    if dt_match and any(w in step_lower for w in ["int", "float", "str", "string", "bool", "boolean", "category", "date", "datetime", "text", "number", "numeric", "decimal", "type"]):
        return "convert_datatype"

    # ── Unit conversion ────────────────────────────────────────────────────────
    unit_pattern = r'\b(' + '|'.join(re.escape(k) for k in [
        'kg to lb', 'lb to kg', 'lbs to kg', 'km to mi', 'mi to km',
        'c to f', 'f to c', 'm to ft', 'ft to m', 'g to kg', 'kg to g',
        'cm to inch', 'inch to cm', 'cm to in', 'in to cm',
        'l to gallon', 'gallon to l', 'liter to gallon', 'gallon to liter',
        'ml to l', 'l to ml', 'ml to liter', 'liter to ml',
    ]) + r')\b'
    if re.search(unit_pattern, step_lower, re.IGNORECASE):
        return "convert_unit"

    # ── Value mapping (handles 0 to No, 0->No, replace 0 with No, change 0 to No, transform X into Y) ─
    has_replace = re.search(r'\b(?:replace|change|convert|turn|make|set|transform)\b', step_lower, re.IGNORECASE)
    has_with_or_to = re.search(r'\b(?:with|to|into|=)\b', step_lower, re.IGNORECASE)
    has_arrow = re.search(r'->|=>|=', step_lower)
    has_pair = re.search(r'\b[a-zA-Z0-9_.\-\$]+\s+(?:to|into|->|=>|=)\s+[a-zA-Z0-9_.\-\$]+\b', step_lower, re.IGNORECASE)

    if (has_replace and has_with_or_to) or has_arrow or has_pair:
        return "replace_value_exact"

    # ── Substring replace ──────────────────────────────────────────────────────
    if re.search(r'\bwherever\b|\bsubstring\b', step_lower, re.IGNORECASE):
        return "replace_value_substring"

    # ── Regex replace ──────────────────────────────────────────────────────────
    if re.search(r'\b(?:remove\s+all\s+non-\w+|regex\s+replace|replace\s+regex)\b',
                 step_lower, re.IGNORECASE):
        return "replace_value_regex"

    # ── Round values (explicit, must be before normalize) ────────────────────
    if re.search(r'\bround\s+to\s+nearest\b|\bround\s+to\s+\d', step_lower, re.IGNORECASE):
        return "round_values"

    # ── Use operation registry for remaining ops ───────────────────────────────
    matches = find_operation_by_keyword(step_lower)
    if not matches:
        return "unsupported"
    if len(matches) == 1:
        return matches[0][0]

    # Multiple candidates: use the most specific (longest alias match)
    return matches[0][0]


def _extract_unit_params(step_lower: str) -> dict:
    """Extract from_unit and to_unit from a unit conversion string."""
    unit_aliases_ordered = sorted(UNIT_CONVERSIONS.keys(), key=lambda t: len(t[0]) + len(t[1]), reverse=True)
    for from_u, to_u in unit_aliases_ordered:
        pattern = rf'\b{re.escape(from_u)}\s+to\s+{re.escape(to_u)}\b'
        if re.search(pattern, step_lower, re.IGNORECASE):
            return {"from_unit": from_u, "to_unit": to_u}
    return {}


def _extract_filter_params(step_str: str) -> dict:
    """Extract filter condition params from a filter/remove rows step."""
    # 1. Standard operator match (e.g. > < >= <= == != =)
    m = re.search(
        r'(?:keep|filter|remove|delete|drop)\s+rows?\s+where\s+'
        r'([a-zA-Z0-9_]+)\s*([><=!]+|==|!=|=)\s*'
        r'([\'"]?[^\'"]+?[\'"]?)(?:\s*$|\s+and\s+)',
        step_str, re.IGNORECASE
    )
    if m:
        return {
            "col": m.group(1).strip(),
            "op": m.group(2).strip(),
            "val": m.group(3).strip().strip("'\""),
        }

    # 2. Textual operator match (e.g. "below 30", "above 30", "less than 30", "greater than 30", "equals 30")
    m2 = re.search(
        r'(?:keep|filter|remove|delete|drop)\s+rows?\s+where\s+'
        r'([a-zA-Z0-9_]+)\s+is\s+(below|above|less\s+than|smaller\s+than|greater\s+than|more\s+than|equal\s+to|equals)\s+'
        r'([\'"]?[^\'"]+?[\'"]?)(?:\s*$|\s+and\s+)',
        step_str, re.IGNORECASE
    )
    if m2:
        col = m2.group(1).strip()
        op_text = m2.group(2).lower().strip()
        val = m2.group(3).strip().strip("'\"")

        op = "<"
        if op_text in ("above", "greater than", "more than"):
            op = ">"
        elif op_text in ("below", "less than", "smaller than"):
            op = "<"
        elif op_text in ("equal to", "equals"):
            op = "=="

        return {"col": col, "op": op, "val": val}

    return {}



def _extract_keep_only_columns(step_str: str, df_columns: list) -> list:
    """Extract column names from a 'keep only X, Y and Z' instruction."""
    m = re.search(r'keep\s+only\s+(.*)', step_str, re.IGNORECASE)
    if not m:
        return []
    raw = m.group(1)
    # Split on comma, 'and', semicolons
    parts = re.split(r'[,;]|\band\b', raw, flags=re.IGNORECASE)
    resolved = []
    for part in parts:
        part = part.strip().strip("'\"")
        if not part:
            continue
        # Try to match to an actual column
        matched, match_type, _ = _find_column_in_text(part, df_columns)
        if matched:
            resolved.append(matched)
        elif part in df_columns:
            resolved.append(part)
        else:
            # Exact name as-is (validation will catch if wrong)
            resolved.append(part)
    return resolved


def build_cleaning_plan(col: str, trans: str, df, target_column: str = None) -> list:
    """
    Build a structured cleaning plan from a column name and transformation string.

    Args:
        col:           The column name this transformation is for. May be None/empty
                       for dataset-scope operations.
        trans:         Raw natural-language transformation instruction.
        df:            The current pandas DataFrame (used for column validation).
        target_column: Optional ML target column name (protected from broad ops).

    Returns:
        List of operation dicts, each with:
            {column, operation, parameters, order, raw_step, message}
    """
    import pandas as pd

    if not trans or not isinstance(trans, str):
        return [{
            "column": col or "",
            "operation": "unsupported",
            "parameters": {},
            "order": 1,
            "raw_step": "",
            "message": f"No transformation specified for '{col}'.",
        }]

    df_columns = list(df.columns) if df is not None else []
    df_dtypes = {c: str(df[c].dtype) for c in df_columns} if df is not None else {}

    # Polish
    polished = _polish_prompt(trans)

    # ── Detect keep-only at the top level (dataset scope) ────────────────────
    if re.search(r'\bkeep\s+only\b', polished, re.IGNORECASE):
        keep_cols = _extract_keep_only_columns(polished, df_columns)
        return [{
            "column": None,
            "operation": "keep_only_columns",
            "parameters": {"columns": keep_cols},
            "order": 1,
            "raw_step": polished,
            "message": f"Keep only columns: {keep_cols}. All other columns will be removed.",
        }]

    # ── Detect dataset-scope drop_null_rows ───────────────────────────────────
    if re.search(r'\b(?:drop|remove|delete)\s+(?:all\s+)?(?:null|nan|missing)\s+rows?\b',
                 polished, re.IGNORECASE):
        return [{
            "column": None,
            "operation": "drop_null_rows",
            "parameters": {},
            "order": 1,
            "raw_step": polished,
            "message": "Remove all rows containing any null/NaN value.",
        }]

    # ── Detect dataset-scope full deduplication ────────────────────────────────
    if re.search(r'\b(?:drop|remove)\s+(?:full\s+)?(?:duplicate|whole\s+duplicate)\s+rows?\b',
                 polished, re.IGNORECASE):
        return [{
            "column": None,
            "operation": "drop_duplicates_full",
            "parameters": {},
            "order": 1,
            "raw_step": polished,
            "message": "Remove all fully-duplicated rows.",
        }]

    # ── Detect vague "clean the dataset" instructions ─────────────────────────
    vague_patterns = [
        r'^clean\s+(?:the\s+)?(?:dataset|data|dataframe|df|file|column|it)\.?$',
        r'^fix\s+(?:the\s+)?(?:dataset|data|dataframe|df|file|column|it|' + re.escape(col or '') + r')\.?$',
        r'^process\s+(?:the\s+)?(?:dataset|data|dataframe|df)\.?$',
    ]
    for vp in vague_patterns:
        if re.match(vp, polished.strip(), re.IGNORECASE):
            return [{
                "column": col or "",
                "operation": "ambiguous_instruction",
                "parameters": {},
                "order": 1,
                "raw_step": polished,
                "message": (
                    f"Instruction '{polished}' is too broad. Please specify the exact operations "
                    f"(e.g., 'fill missing with median', 'remove duplicates', 'convert to int')."
                ),
            }]

    # ── Split chained steps ────────────────────────────────────────────────────
    steps = _STEP_SPLIT_PATTERN.split(polished)
    steps = [s.strip() for s in steps if s.strip()]

    plan = []
    for order_idx, step_str in enumerate(steps, start=1):
        step_lower = step_str.lower()
        operation = _detect_operation(step_lower)
        parameters = {}
        message = ""

        # ── Resolve target column for this step ────────────────────────────────
        step_col = col  # default: use the column passed in

        # ── Extract parameters per operation ───────────────────────────────────

        if operation == "keep_column":
            message = f"Column '{step_col}' marked as unchanged. No modification applied."

        elif operation == "keep_only_columns":
            keep_cols = _extract_keep_only_columns(step_str, df_columns)
            parameters["columns"] = keep_cols
            step_col = None
            message = f"Keep only columns: {keep_cols}."

        elif operation == "convert_datatype":
            dt_match = re.search(
                r'\b(?:convert\s+to|cast\s+to|change\s+type\s+to|to|as)\s+'
                r'(int(?:eger)?|float|str(?:ing)?|bool(?:ean)?|categor(?:y|ical)|datetime|date|text|object)',
                step_lower, re.IGNORECASE
            )
            if dt_match:
                raw_dtype = dt_match.group(1).strip()
                canonical = resolve_dtype_target(raw_dtype)
                parameters["dtype"] = canonical or raw_dtype
            message = f"Convert '{step_col}' to dtype '{parameters.get('dtype', 'unknown')}'."

        elif operation == "convert_unit":
            parameters = _extract_unit_params(step_lower)
            message = (f"Convert '{step_col}' from {parameters.get('from_unit')} "
                       f"to {parameters.get('to_unit')}.")

        elif operation == "replace_value_exact":
            mapping = _extract_value_mapping(step_str, step_col or "")
            parameters["mapping"] = mapping
            desc = ", ".join([f"'{k}'→'{v}'" for k, v in mapping.items()])
            message = f"Replace values in '{step_col}': {desc}."

        elif operation == "replace_value_substring":
            # "replace X wherever it appears with Y"
            m = re.search(r"replace\s+['\"]?(.+?)['\"]?\s+wherever.*?with\s+['\"]?(.+?)['\"]?$",
                          step_str, re.IGNORECASE)
            if m:
                parameters["old"] = m.group(1).strip()
                parameters["new"] = m.group(2).strip()
            message = f"Replace substring '{parameters.get('old')}' with '{parameters.get('new')}' in '{step_col}'."

        elif operation == "replace_value_regex":
            # "remove all non-numeric characters from Phone"
            m = re.search(r"remove\s+all\s+(non-[\w]+)\s+characters?", step_str, re.IGNORECASE)
            if m:
                char_class = m.group(1).lower()
                if "non-numeric" in char_class or "non-digit" in char_class:
                    parameters["pattern"] = r'[^\d]'
                    parameters["replacement"] = ''
                elif "non-alpha" in char_class:
                    parameters["pattern"] = r'[^a-zA-Z]'
                    parameters["replacement"] = ''
                else:
                    parameters["pattern"] = r'[^\w]'
                    parameters["replacement"] = ''
            message = f"Regex replace in '{step_col}': pattern='{parameters.get('pattern')}'."

        elif operation == "drop_duplicates_by_columns":
            keep = "first"
            if re.search(r'\blast\b', step_lower, re.IGNORECASE):
                keep = "last"
            elif re.search(r'\bnone\b|\ball\b|\bno\s+keep\b', step_lower, re.IGNORECASE):
                keep = False
            parameters["keep"] = keep
            parameters["subset"] = [step_col] if step_col else []
            message = (f"Remove duplicate rows based on '{step_col}', "
                       f"keeping {'first' if keep == 'first' else keep} occurrence.")

        elif operation == "drop_null_rows_column":
            parameters["column"] = step_col
            message = f"Remove rows where '{step_col}' is null."

        elif operation in ("filter_rows", "remove_rows"):
            parameters = _extract_filter_params(step_str)
            step_col = None  # dataset scope
            cond = f"{parameters.get('col')} {parameters.get('op')} {parameters.get('val')}"
            action = "Keep" if operation == "filter_rows" else "Remove"
            message = f"{action} rows where {cond}."

        elif operation == "split_column":
            sep_m = re.search(r'split\s+(?:column\s+)?by\s+[\'"]?([^\'"]+?)[\'"]?$',
                               step_str, re.IGNORECASE)
            sep = sep_m.group(1) if sep_m else ' '
            if sep.lower() == 'space': sep = ' '
            elif sep.lower() == 'comma': sep = ','
            elif sep.lower() == 'tab': sep = '\t'
            parameters["separator"] = sep
            message = f"Split '{step_col}' by '{sep}'."

        elif operation == "concat_column":
            m = re.search(r'(?:concat(?:enate)?|combine)\s+with\s+[\'"]?([a-zA-Z0-9_]+)[\'"]?',
                          step_str, re.IGNORECASE)
            if m:
                parameters["other_col"] = m.group(1).strip()
            message = f"Concatenate '{step_col}' with '{parameters.get('other_col')}'."

        elif operation == "rename_column":
            m = re.search(r'rename(?:\s+column)?\s+to\s+[\'"]?([a-zA-Z0-9_]+)[\'"]?',
                          step_str, re.IGNORECASE)
            if m:
                parameters["new_name"] = m.group(1).strip()
            message = f"Rename '{step_col}' to '{parameters.get('new_name')}'."

        elif operation == "bin_column":
            m = re.search(r'(?:bin|bucket)\s+(?:into\s+)?(\d+)', step_str, re.IGNORECASE)
            parameters["num_bins"] = int(m.group(1)) if m else 4
            message = f"Bin '{step_col}' into {parameters['num_bins']} groups."

        elif operation == "ordinal_encode":
            m = re.search(r'ordinal(?:\s+order)?\s*:\s*([^;,\n]+)', step_str, re.IGNORECASE)
            if m:
                order_items = [x.strip() for x in m.group(1).split(',') if x.strip()]
                parameters["order"] = order_items
            message = f"Ordinal encode '{step_col}'."

        elif operation == "impute_custom":
            # "fill with Unknown" / "replace missing with 'N/A'"
            m = re.search(
                r'(?:fill(?:\s+missing|\s+null|\s+na)?(?:\s+values?)?\s+with|'
                r'replace\s+missing\s+with|fill\s+na\s+with|impute\s+with)\s+'
                r'[\'"]?([^\'"]+?)[\'"]?$',
                step_str, re.IGNORECASE
            )
            if m:
                parameters["fill_value"] = m.group(1).strip()
            message = f"Fill missing '{step_col}' with '{parameters.get('fill_value')}'."

        elif operation == "round_values":
            m = re.search(r'round\s+to\s+(\d+)', step_str, re.IGNORECASE)
            parameters["decimals"] = int(m.group(1)) if m else 0
            message = f"Round '{step_col}' to {parameters['decimals']} decimal places."

        elif operation == "derived_math":
            m = re.search(r'(multiply|add|subtract|divide)\s+by\s+([a-zA-Z0-9_]+)',
                          step_str, re.IGNORECASE)
            if m:
                parameters["operation"] = m.group(1).lower()
                parameters["target"] = m.group(2).strip()
            message = (f"Derived: '{step_col}' {parameters.get('operation')} "
                       f"'{parameters.get('target')}'.")

        elif operation == "date_difference":
            m = re.search(r'(?:days since|date diff(?:erence)?)\s+([a-zA-Z0-9_]+)',
                          step_str, re.IGNORECASE)
            if m:
                ref = m.group(1).strip()
                parameters["ref_col"] = None if ref.lower() == 'today' else ref
                parameters["use_today"] = (ref.lower() == 'today')
            message = f"Date difference for '{step_col}'."

        elif operation == "unsupported":
            message = (
                f"Operation in step '{step_str}' is not recognized. "
                f"No changes will be made to '{step_col}'. "
                "Please rephrase your instruction (e.g., 'fill missing with median', "
                "'convert to integer', 'remove duplicates based on column')."
            )

        else:
            message = f"Apply '{operation}' to '{step_col}'."

        plan.append({
            "column": step_col,
            "operation": operation,
            "parameters": parameters,
            "order": order_idx,
            "raw_step": step_str,
            "message": message,
        })

    return plan
