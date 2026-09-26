"""
Fix _extract_value_mapping in intent_parser.py by writing a clean replacement.
"""
import re

content = open('services/cleaning/intent_parser.py', encoding='utf-8').read()

# Find boundaries
start_idx = content.find('def _extract_value_mapping')
end_idx = content.find('\ndef _detect_operation')

new_func = r'''def _extract_value_mapping(step_str: str, col_name: str) -> dict:
    """
    Extract value replacement mappings from human language step strings.
    Handles:
        replace '0' with 'No' and '1' with 'Yes'
        0 -> No, 1 -> Yes
        0 to No, 1 to Yes
        change 0 to No and 1 to Yes
        0 = No, 1 = Yes
        make 0 No and 1 Yes
        map 0 as Male and 1 as Female
        change value of 0 to Male and 1 to Female
        replace Tesla with Tesla Motors
    """
    col_lower = (col_name or "").lower()
    stop_words = {'where', 'there', 'is', 'replace', 'it', 'with', 'in',
                  'and', 'column', 'columns', 'transform', 'convert', 'change',
                  'make', 'turn', 'set', 'the',
                  'values', 'each', 'all', 'data', 'dataset', col_lower}

    mapping = {}

    # Strip out column name prefix if present at start
    clean_step = step_str
    if col_name and clean_step.lower().startswith(col_lower):
        clean_step = clean_step[len(col_name):].strip()

    # Strip leading verb keywords (including "map")
    clean_step = re.sub(r'^(?:transform|convert|change|replace|set|make|map)\s+', '', clean_step, flags=re.IGNORECASE).strip()
    # Strip "value of / values of / value" noise prefix (e.g. "value of 0 to Male")
    clean_step = re.sub(r'^(?:value\s+of|values\s+of|value|values)\s+', '', clean_step, flags=re.IGNORECASE).strip()
    # Strip column noise words
    clean_step = re.sub(r'\b(?:column|col|columns|feature|attribute)\s+', '', clean_step, flags=re.IGNORECASE).strip()

    # Pattern 0: "X as Y" pairs — "0 as Male and 1 as Female"
    p0 = re.findall(
        r"""['\"]?([a-zA-Z0-9_.\-\$\s]+?)['\"]?\s+(?:as)\s+['\"]?([a-zA-Z0-9_.\-\$\s]+?)['\"]?(?:\s+and\s+|$|,)""",
        clean_step, re.IGNORECASE
    )
    for old_v, new_v in p0:
        old_v, new_v = old_v.strip(), new_v.strip()
        if old_v.lower() not in stop_words and new_v.lower() not in stop_words and old_v and new_v:
            mapping[old_v] = new_v

    if mapping:
        return mapping

    # Pattern 1: Explicit 'X' with/to/into 'Y'
    p1 = re.findall(
        r"""(?:transform|replace|change|convert|turn|make|set)?\s*['\"]?([^'\"]+?)['\"]?\s+(?:with|to|into|=)\s+['\"]?([^'\"]+?)['\"]?(?:\s+and\s+|$|,)""",
        clean_step, re.IGNORECASE
    )
    for old_v, new_v in p1:
        old_v, new_v = old_v.strip(), new_v.strip()
        if old_v.lower() not in stop_words and new_v.lower() not in stop_words and old_v and new_v:
            mapping[old_v] = new_v

    if mapping:
        return mapping

    # Pattern 2: Arrow or Equals pairs: X -> Y, X => Y, X = Y
    p2 = re.findall(
        r"""['\"]?([^'\"]+?)['\"]?\s*(?:->|=>|=)\s*['\"]?([^'\"]+?)['\"]?(?:\s+and\s+|$|,)""",
        clean_step, re.IGNORECASE
    )
    for old_v, new_v in p2:
        old_v, new_v = old_v.strip(), new_v.strip()
        if old_v.lower() not in stop_words and new_v.lower() not in stop_words and old_v and new_v:
            mapping[old_v] = new_v

    if mapping:
        return mapping

    # Pattern 3: Shorthand "X to Y" pairs — "0 to Male, 1 to Female"
    # Use minimal stop set so that simple pairs like "0 to Male" work
    _to_stops = {'and', 'or', 'the', 'a', 'an', 'of', col_lower}
    p3 = re.findall(
        r"""\b([a-zA-Z0-9_.\-\$]+)\s+(?:to|into)\s+([a-zA-Z0-9_.\-\$\s]+?)(?:\s+and\s+|$|,)""",
        clean_step, re.IGNORECASE
    )
    for old_v, new_v in p3:
        old_v, new_v = old_v.strip(), new_v.strip()
        if old_v.lower() not in _to_stops and new_v.lower() not in _to_stops and old_v and new_v:
            mapping[old_v] = new_v

    return mapping

'''

new_content = content[:start_idx] + new_func + content[end_idx:]
open('services/cleaning/intent_parser.py', 'w', encoding='utf-8').write(new_content)
print("Patched successfully. Total lines:", new_content.count('\n'))
