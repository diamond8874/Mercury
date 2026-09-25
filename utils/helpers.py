import json
import logging
import pandas as pd
from config import ALLOWED_EXTENSIONS

logger = logging.getLogger(__name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def parse_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)

def read_csv_robust(file_path: str, **kwargs) -> pd.DataFrame:
    """
    Read a CSV file with robust multi-encoding fallback.
    Tries utf-8, latin-1 (iso-8859-1 / cp1252), utf-8-sig, and lastly errors='replace'.
    """
    encodings = ["utf-8", "latin-1", "utf-8-sig", "cp1252"]
    last_exc = None
    for enc in encodings:
        try:
            return pd.read_csv(file_path, encoding=enc, **kwargs)
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_exc = exc
            continue

    logger.warning("All standard encodings failed for %s, falling back to encoding_errors='replace'", file_path)
    return pd.read_csv(file_path, encoding="utf-8", encoding_errors="replace", **kwargs)
