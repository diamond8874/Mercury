"""
Fix _detect_operation value mapping lines in intent_parser.py using line index.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

content = open('services/cleaning/intent_parser.py', encoding='utf-8').read()
lines = content.split('\n')

# Find the line index of the value mapping block
start_line = None
for i, line in enumerate(lines):
    if 'Value mapping' in line and 'replace 0 with No' in line:
        start_line = i
        break

if start_line is None:
    print("ERROR: could not find start line")
    exit(1)

print(f"Found block at line {start_line}")

# Find end of block (return "unsupported")
end_line = None
for i in range(start_line, min(start_line + 20, len(lines))):
    if 'return "unsupported"' in lines[i]:
        end_line = i
        break

if end_line is None:
    print("ERROR: could not find end line")
    exit(1)

print(f"Block from line {start_line} to {end_line}, replacing...")

# Replacement block - exact lines to replace
new_lines = [
    "    # -- Value mapping (handles 0->No, replace 0 with No, change 0 to No, 0 to No 1 to Yes, map 0 as Male) --",
    "    has_arrow = re.search(r'->|=>|=', step_lower)",
    r"    has_as_pair = re.search(r'\b[a-zA-Z0-9_.\-\$]+\s+as\s+[a-zA-Z0-9_.\-\$]+\b', step_lower, re.IGNORECASE)",
    r"    has_pair = re.search(r'\b[a-zA-Z0-9_.\-\$]+\s+(?:to|into|with)\s+[a-zA-Z0-9_.\-\$]+\b', step_lower, re.IGNORECASE)",
    r"    has_verb = re.search(r'\b(?:replace|change|convert|turn|make|set|map)\b', step_lower, re.IGNORECASE)",
    r"    # Multiple 'X to/as/with Y' pairs in one prompt = unambiguous value-list mapping",
    r"    has_multi_pair = len(re.findall(r'\b[a-zA-Z0-9_.\-\$]+\s+(?:to|into|with|as)\s+[a-zA-Z0-9_.\-\$]+\b', step_lower, re.IGNORECASE)) >= 2",
    r'    if has_arrow or has_as_pair or (has_pair and has_verb) or has_multi_pair:',
    r'        return "replace_value_exact"',
    r'',
    r'    return "unsupported"',
]

lines[start_line:end_line+1] = new_lines
new_content = '\n'.join(lines)
open('services/cleaning/intent_parser.py', 'w', encoding='utf-8').write(new_content)
print("Patched successfully!")
