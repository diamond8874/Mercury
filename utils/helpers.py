import json
from config import ALLOWED_EXTENSIONS

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_json_response(text):
    """
    Extract a JSON object from a model reply.

    Only OpenAI-compatible providers reliably honour ``response_format:
    json_object``; the rest routinely wrap their JSON in a markdown fence or
    lead with a sentence of prose. Being strict here would push those providers
    into the offline fallback on every call, so we try three strategies in
    order: parse as-is, strip a markdown fence, then locate the outermost
    balanced ``{...}`` block.

    Raises ``ValueError`` when no JSON object can be recovered.
    """
    if not text or not text.strip():
        raise ValueError("Empty response - no JSON to parse.")

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    fenced = _strip_code_fence(text)
    if fenced != text:
        try:
            return json.loads(fenced)
        except json.JSONDecodeError:
            text = fenced

    block = _outermost_json_object(text)
    if block is not None:
        try:
            return json.loads(block)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Found a JSON-like block but could not parse it: {exc}") from exc

    raise ValueError("No JSON object found in the response.")


def _strip_code_fence(text):
    """Remove a leading ```json / trailing ``` wrapper if present."""
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    lines = lines[1:]                       # drop the opening fence
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _outermost_json_object(text):
    """
    Return the first balanced ``{...}`` substring, or None.

    Brace counting ignores braces inside string literals and honours backslash
    escapes, so reasons containing '{' or '"' do not break the scan.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    return None
