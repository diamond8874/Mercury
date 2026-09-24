"""
utils/upload_validator.py
--------------------------
4D §1: Deep upload validation with content sniffing, decompression-bomb
protection, macro/external-link detection, and configurable row/column caps.

All tunables are read from environment variables so they can be overridden
in .env without touching code:

  MAX_ROWS          (default 200 000)
  MAX_COLS          (default 500)
  MAX_XLSX_SHEETS   (default 10)
  MAX_UNCOMPRESSED_BYTES  (default 200 MB)
"""
import io
import os
import logging
import zipfile
from typing import Tuple, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurable limits (environment-overridable)
# ---------------------------------------------------------------------------
MAX_ROWS: int = int(os.environ.get("MAX_ROWS", 200_000))
MAX_COLS: int = int(os.environ.get("MAX_COLS", 500))
MAX_XLSX_SHEETS: int = int(os.environ.get("MAX_XLSX_SHEETS", 10))
# Decompression-bomb guard: reject xlsx whose *uncompressed* total size
# exceeds this threshold (default 200 MB).
MAX_UNCOMPRESSED_BYTES: int = int(
    os.environ.get("MAX_UNCOMPRESSED_BYTES", 200 * 1024 * 1024)
)

# Magic bytes for content sniffing
_XLSX_MAGIC = b"PK\x03\x04"          # zip / Office Open XML
_XLS_MAGIC = b"\xd0\xcf\x11\xe0"     # OLE2 compound document
_CSV_SNIFFER_SAMPLE = 8192            # bytes fed to csv.Sniffer


def _check_decompression_bomb(path: str) -> Optional[str]:
    """
    Open the zip container of an xlsx/xls-as-zip and sum the
    uncompressed sizes.  Returns an error message or None.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            total = sum(info.file_size for info in zf.infolist())
            if total > MAX_UNCOMPRESSED_BYTES:
                return (
                    f"File rejected: uncompressed size {total // (1024*1024)} MB "
                    f"exceeds the {MAX_UNCOMPRESSED_BYTES // (1024*1024)} MB limit."
                )
    except zipfile.BadZipFile:
        # Not a zip -- may be legacy .xls (OLE2), skip this check
        pass
    except Exception as exc:
        logger.warning("Decompression-bomb check failed (%s): %s", path, exc)
    return None


def _check_xlsx_macros_and_links(path: str) -> Optional[str]:
    """
    Inspect the zip members of an xlsx for:
      - vbaProject.bin  -> macro-enabled workbook
      - externalLinks/  -> external link references
    Returns an error message or None.
    """
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names_lower = {n.lower() for n in zf.namelist()}
            if any("vbaproject.bin" in n for n in names_lower):
                return "File rejected: macro-enabled workbooks (.xlsm) are not allowed."
            if any("externallinks/" in n for n in names_lower):
                return "File rejected: workbook contains external link references."
    except zipfile.BadZipFile:
        pass
    except Exception as exc:
        logger.warning("Macro/link check failed (%s): %s", path, exc)
    return None


def _sniff_extension(path: str, declared_ext: str) -> Optional[str]:
    """
    Read the first 8 bytes and compare against known magic numbers.
    Returns an error string if the content does not match the declared
    extension, or None if OK.
    """
    try:
        with open(path, "rb") as fh:
            magic = fh.read(8)
    except OSError as exc:
        return f"Cannot read uploaded file: {exc}"

    if declared_ext in ("xlsx",):
        if not magic.startswith(_XLSX_MAGIC):
            return "File content does not match its .xlsx extension."
    elif declared_ext == "xls":
        if not (magic.startswith(_XLS_MAGIC) or magic.startswith(_XLSX_MAGIC)):
            return "File content does not match its .xls extension."
    elif declared_ext == "csv":
        if magic.startswith(_XLSX_MAGIC) or magic.startswith(_XLS_MAGIC):
            return (
                "File content appears to be a binary Excel file "
                "but was uploaded with a .csv extension."
            )
    return None


def validate_upload(file_path: str, file_ext: str) -> Tuple[bool, Optional[str]]:
    """
    Full validation pipeline for an already-saved upload.

    Returns (True, None) on success, (False, error_message) on failure.

    Steps:
      1. Content sniffing (magic bytes vs declared extension)
      2. Decompression-bomb guard (xlsx only)
      3. Macro / external-link detection (xlsx only)
      4. Parse with pandas inside row/column caps
    """
    # -- 1. Content sniff ------------------------------------------------
    sniff_err = _sniff_extension(file_path, file_ext)
    if sniff_err:
        return False, sniff_err

    # -- 2 & 3. xlsx-specific checks ------------------------------------
    if file_ext in ("xlsx", "xls"):
        bomb_err = _check_decompression_bomb(file_path)
        if bomb_err:
            return False, bomb_err
        macro_err = _check_xlsx_macros_and_links(file_path)
        if macro_err:
            return False, macro_err

    # -- 4. Parse + shape caps ------------------------------------------
    try:
        if file_ext in ("xlsx", "xls"):
            xl = pd.ExcelFile(file_path)
            if len(xl.sheet_names) > MAX_XLSX_SHEETS:
                return (
                    False,
                    f"Workbook has {len(xl.sheet_names)} sheets; "
                    f"maximum allowed is {MAX_XLSX_SHEETS}.",
                )
            df = pd.read_excel(
                file_path,
                sheet_name=xl.sheet_names[0],
                nrows=MAX_ROWS + 1,
            )
        else:
            df = pd.read_csv(file_path, nrows=MAX_ROWS + 1)

        rows, cols = df.shape
        if rows > MAX_ROWS:
            return (
                False,
                f"Dataset has more than {MAX_ROWS:,} rows. "
                "Please upload a smaller sample.",
            )
        if cols > MAX_COLS:
            return (
                False,
                f"Dataset has {cols} columns; maximum allowed is {MAX_COLS}.",
            )
    except MemoryError:
        return False, "File is too large to process in memory."
    except Exception as exc:
        return False, f"Failed to parse file: {exc}"

    return True, None
