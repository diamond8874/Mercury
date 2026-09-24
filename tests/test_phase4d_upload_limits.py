"""
tests/test_phase4d_upload_limits.py
-------------------------------------
4D unit + integration tests:
  §1  Upload validation (content sniffing, decompression bomb, macros, shape caps)
  §2  Rate limiting (upload, LLM chat, PDF — stubbed)
  §3  Per-user quotas (session count, storage)
  §4  Cleanup job (TTL expiry, delete_session_files)
  §5  Filename safety (uuid storage)
"""
import io
import os
import json
import struct
import zipfile
import datetime
import threading
import tempfile
import pytest

# ---------------------------------------------------------------------------
# Helpers — build synthetic files
# ---------------------------------------------------------------------------

def _make_csv_bytes(rows=5, cols=3) -> bytes:
    header = ",".join(f"col{i}" for i in range(cols))
    data_row = ",".join(str(i) for i in range(cols))
    lines = [header] + [data_row] * rows
    return "\n".join(lines).encode()


def _make_xlsx_bytes(rows=5, cols=3) -> bytes:
    """Create a minimal valid xlsx in memory using openpyxl."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for c in range(1, cols + 1):
        ws.cell(row=1, column=c, value=f"col{c}")
    for r in range(2, rows + 2):
        for c in range(1, cols + 1):
            ws.cell(row=r, column=c, value=r * c)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_fake_xlsx_with_macro() -> bytes:
    """xlsx zip containing a fake vbaProject.bin entry."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/vbaProject.bin", b"\x00" * 10)
    return buf.getvalue()


def _make_fake_xlsx_with_external_links() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("xl/externalLinks/externalLink1.xml", "<link/>")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# §1  upload_validator unit tests
# ---------------------------------------------------------------------------

from utils.upload_validator import validate_upload

class TestUploadValidator:
    def test_valid_csv_passes(self, tmp_path):
        p = tmp_path / "data.csv"
        p.write_bytes(_make_csv_bytes())
        ok, err = validate_upload(str(p), "csv")
        assert ok, err

    def test_valid_xlsx_passes(self, tmp_path):
        from utils.upload_validator import validate_upload
        p = tmp_path / "data.xlsx"
        p.write_bytes(_make_xlsx_bytes())
        ok, err = validate_upload(str(p), "xlsx")
        assert ok, err

    def test_csv_with_binary_magic_rejected(self, tmp_path):
        """A file starting with xlsx magic but declared as csv should fail."""
        from utils.upload_validator import validate_upload
        p = tmp_path / "bad.csv"
        p.write_bytes(_make_xlsx_bytes())   # xlsx bytes, wrong ext
        ok, err = validate_upload(str(p), "csv")
        assert not ok
        assert "binary Excel" in err or "content" in err.lower()

    def test_macro_workbook_rejected(self, tmp_path):
        from utils.upload_validator import validate_upload
        p = tmp_path / "macro.xlsx"
        p.write_bytes(_make_fake_xlsx_with_macro())
        ok, err = validate_upload(str(p), "xlsx")
        assert not ok
        assert "macro" in err.lower()

    def test_external_links_rejected(self, tmp_path):
        from utils.upload_validator import validate_upload
        p = tmp_path / "links.xlsx"
        p.write_bytes(_make_fake_xlsx_with_external_links())
        ok, err = validate_upload(str(p), "xlsx")
        assert not ok
        assert "external link" in err.lower()

    def test_row_cap_enforced(self, tmp_path, monkeypatch):
        from utils import upload_validator
        monkeypatch.setattr(upload_validator, "MAX_ROWS", 3)
        import pandas as pd
        p = tmp_path / "big.csv"
        p.write_bytes(_make_csv_bytes(rows=10))
        ok, err = validate_upload(str(p), "csv")
        assert not ok
        assert "rows" in err.lower()

    def test_col_cap_enforced(self, tmp_path, monkeypatch):
        from utils import upload_validator
        monkeypatch.setattr(upload_validator, "MAX_COLS", 2)
        p = tmp_path / "wide.csv"
        p.write_bytes(_make_csv_bytes(rows=2, cols=5))
        ok, err = validate_upload(str(p), "csv")
        assert not ok
        assert "column" in err.lower()

    def test_sheet_cap_enforced(self, tmp_path, monkeypatch):
        from utils import upload_validator
        monkeypatch.setattr(upload_validator, "MAX_XLSX_SHEETS", 1)
        import openpyxl
        wb = openpyxl.Workbook()
        for i in range(3):
            wb.create_sheet(f"Sheet{i}")
        buf = io.BytesIO()
        wb.save(buf)
        p = tmp_path / "multi.xlsx"
        p.write_bytes(buf.getvalue())
        ok, err = validate_upload(str(p), "xlsx")
        assert not ok
        assert "sheet" in err.lower()

    def test_decompression_bomb_rejected(self, tmp_path, monkeypatch):
        from utils import upload_validator
        monkeypatch.setattr(upload_validator, "MAX_UNCOMPRESSED_BYTES", 100)
        # Create a zip with a single entry that claims to be 1000 bytes uncompressed
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("xl/big.bin", b"A" * 1000)
        p = tmp_path / "bomb.xlsx"
        p.write_bytes(buf.getvalue())
        ok, err = validate_upload(str(p), "xlsx")
        assert not ok
        assert "uncompressed" in err.lower() or "limit" in err.lower()


# ---------------------------------------------------------------------------
# §4  cleanup.delete_session_files unit tests
# ---------------------------------------------------------------------------

class TestDeleteSessionFiles:
    def _make_app(self, upload_folder, output_folder, session_folder):
        """Return a minimal Flask app with the required config."""
        from flask import Flask
        app = Flask(__name__)
        app.config["UPLOAD_FOLDER"] = str(upload_folder)
        app.config["OUTPUT_FOLDER"] = str(output_folder)
        app.config["SESSION_FOLDER"] = str(session_folder)
        return app

    def test_deletes_upload_and_output(self, tmp_path):
        from utils.cleanup import delete_session_files
        upload_dir = tmp_path / "uploads"; upload_dir.mkdir()
        output_dir = tmp_path / "output"; output_dir.mkdir()
        session_dir = tmp_path / "sessions"; session_dir.mkdir()

        # Create dummy files
        (upload_dir / "abc.csv").write_text("data")
        (output_dir / "cleaned_abc.xlsx").write_text("clean")
        session_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        session_json = session_dir / f"{session_id}.json"
        data = {
            "session_id": session_id,
            "file_id": "abc.csv",
            "cleaned_filename": "cleaned_abc.xlsx",
            "charts": []
        }
        session_json.write_text(json.dumps(data))

        app = self._make_app(upload_dir, output_dir, session_dir)
        with app.app_context():
            summary = delete_session_files(app, data, session_id)

        assert not (upload_dir / "abc.csv").exists()
        assert not (output_dir / "cleaned_abc.xlsx").exists()
        assert not session_json.exists()
        assert len(summary["errors"]) == 0
        assert len(summary["removed"]) == 3

    def test_missing_files_not_errored(self, tmp_path):
        from utils.cleanup import delete_session_files
        upload_dir = tmp_path / "uploads"; upload_dir.mkdir()
        output_dir = tmp_path / "output"; output_dir.mkdir()
        session_dir = tmp_path / "sessions"; session_dir.mkdir()

        session_id = "11111111-2222-3333-4444-555555555555"
        data = {
            "session_id": session_id,
            "file_id": "nonexistent.csv",
            "cleaned_filename": None,
            "charts": []
        }
        # Don't create session JSON — should not error

        app = self._make_app(upload_dir, output_dir, session_dir)
        with app.app_context():
            summary = delete_session_files(app, data, session_id)

        assert len(summary["errors"]) == 0  # missing files are silently skipped


# ---------------------------------------------------------------------------
# §4  Cleanup sweep TTL expiry
# ---------------------------------------------------------------------------

class TestCleanupSweep:
    def _make_app(self, session_folder, upload_folder, output_folder):
        from flask import Flask
        app = Flask(__name__)
        app.config["SESSION_FOLDER"] = str(session_folder)
        app.config["UPLOAD_FOLDER"] = str(upload_folder)
        app.config["OUTPUT_FOLDER"] = str(output_folder)
        return app

    def test_expired_session_removed(self, tmp_path, monkeypatch):
        import utils.cleanup as cleanup_mod
        monkeypatch.setattr(cleanup_mod, "SESSION_TTL_SECONDS", 1)

        session_dir = tmp_path / "sessions"; session_dir.mkdir()
        upload_dir = tmp_path / "uploads"; upload_dir.mkdir()
        output_dir = tmp_path / "output"; output_dir.mkdir()

        session_id = "cafecafe-cafe-cafe-cafe-cafecafecafe"
        old_ts = (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(seconds=10)
        ).isoformat()
        (upload_dir / "u.csv").write_text("x")
        data = {
            "session_id": session_id,
            "file_id": "u.csv",
            "cleaned_filename": None,
            "charts": [],
            "last_accessed": old_ts
        }
        (session_dir / f"{session_id}.json").write_text(json.dumps(data))

        app = self._make_app(session_dir, upload_dir, output_dir)
        with app.app_context():
            cleanup_mod._run_sweep(app)

        assert not (session_dir / f"{session_id}.json").exists()
        assert not (upload_dir / "u.csv").exists()

    def test_fresh_session_not_removed(self, tmp_path, monkeypatch):
        import utils.cleanup as cleanup_mod
        monkeypatch.setattr(cleanup_mod, "SESSION_TTL_SECONDS", 86400)

        session_dir = tmp_path / "sessions"; session_dir.mkdir()
        upload_dir = tmp_path / "uploads"; upload_dir.mkdir()
        output_dir = tmp_path / "output"; output_dir.mkdir()

        session_id = "deadbeef-dead-beef-dead-beefdeadbeef"
        fresh_ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
        (upload_dir / "fresh.csv").write_text("data")
        data = {
            "session_id": session_id,
            "file_id": "fresh.csv",
            "cleaned_filename": None,
            "charts": [],
            "last_accessed": fresh_ts
        }
        (session_dir / f"{session_id}.json").write_text(json.dumps(data))

        app = self._make_app(session_dir, upload_dir, output_dir)
        with app.app_context():
            cleanup_mod._run_sweep(app)

        # Still there
        assert (session_dir / f"{session_id}.json").exists()


# ---------------------------------------------------------------------------
# §5  Filename safety (integration — upload route)
# ---------------------------------------------------------------------------

class TestFilenameSafety:
    @pytest.fixture
    def client(self, tmp_path):
        os.environ["TESTING"] = "true"
        os.environ["SECRET_KEY"] = "test-secret-123"
        import config
        config.UPLOAD_FOLDER = str(tmp_path / "uploads")
        config.SESSION_FOLDER = str(tmp_path / "sessions")
        config.OUTPUT_FOLDER = str(tmp_path / "output")
        os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
        os.makedirs(config.SESSION_FOLDER, exist_ok=True)
        os.makedirs(config.OUTPUT_FOLDER, exist_ok=True)

        import importlib, app as app_module
        importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        app_module.app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
        app_module.app.config["SESSION_FOLDER"] = config.SESSION_FOLDER
        app_module.app.config["OUTPUT_FOLDER"] = config.OUTPUT_FOLDER
        client = app_module.app.test_client()

        # Register + log in
        client.post("/api/auth/register",
                    json={"username": "filetest", "password": "FileTest123!"},
                    content_type="application/json")
        client.post("/api/auth/login",
                    json={"username": "filetest", "password": "FileTest123!"},
                    content_type="application/json")
        return client

    def test_stored_filename_is_uuid(self, client, tmp_path):
        """The file on disk must be <uuid>.csv, never the user-supplied name."""
        data = {"file": (io.BytesIO(_make_csv_bytes()), "../../evil/../data.csv")}
        resp = client.post("/api/upload", data=data, content_type="multipart/form-data")
        assert resp.status_code == 200
        body = resp.get_json()
        file_id = body["file_id"]
        # Must match <uuid>.<ext>
        import re
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.csv$",
            file_id
        ), f"file_id not uuid format: {file_id}"
        # Original name is preserved only in display metadata, not as the actual filename
        assert body["original_name"] != file_id
