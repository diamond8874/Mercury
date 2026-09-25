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
    Production-grade hybrid CSV reader:
    1. Probes a 64KB sample with charset-normalizer (<10ms overhead even on 100MB+ files).
    2. If confidence is high, parses with the auto-detected encoding.
    3. Falls back gracefully to priority ladder: utf-8 -> utf-8-sig -> cp1252 -> latin-1.
    4. Safe last resort: encoding_errors='replace'.
    """
    # 1. Fast sample probe using charset-normalizer (bounded sample to avoid 30s delays on 100MB files)
    try:
        import charset_normalizer
        with open(file_path, "rb") as f:
            sample = f.read(65536)  # 64 KB sample
        if sample:
            match = charset_normalizer.from_bytes(sample).best()
            if match and match.encoding:
                detected_enc = match.encoding
                try:
                    return pd.read_csv(file_path, encoding=detected_enc, **kwargs)
                except (UnicodeDecodeError, UnicodeError, LookupError):
                    logger.debug("Detected encoding '%s' failed full parse, falling back to priority list.", detected_enc)
    except Exception as probe_err:
        logger.debug("Charset normalization probe error on %s: %s", file_path, probe_err)

    # 2. Resilient priority fallback ladder
    encodings = ["utf-8", "utf-8-sig", "cp1252", "latin-1"]
    for enc in encodings:
        try:
            return pd.read_csv(file_path, encoding=enc, **kwargs)
        except (UnicodeDecodeError, UnicodeError):
            continue

    # 3. Ultimate non-blocking safety net
    logger.warning("All encodings failed for %s, falling back to encoding_errors='replace'", file_path)
    return pd.read_csv(file_path, encoding="utf-8", encoding_errors="replace", **kwargs)

def sanitize_dataframe_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """
    Strips non-printable control characters (ASCII 0-8, 11-12, 14-31) that cause
    openpyxl IllegalCharacterError ('... cannot be used in worksheets').
    """
    from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
    df_clean = df.copy()
    for col in df_clean.select_dtypes(include=['object', 'string']).columns:
        df_clean[col] = df_clean[col].apply(
            lambda val: ILLEGAL_CHARACTERS_RE.sub('', val) if isinstance(val, str) else val
        )
    return df_clean

def safe_to_excel(df: pd.DataFrame, output_path: str, index: bool = False, **kwargs) -> None:
    """
    Safely exports a DataFrame to an Excel workbook (.xlsx), stripping illegal XML control
    characters so openpyxl never throws IllegalCharacterError.
    """
    clean_df = sanitize_dataframe_for_excel(df)
    clean_df.to_excel(output_path, index=index, engine='openpyxl', **kwargs)
