import os
import json
import logging
import datetime
from flask import current_app
import pandas as pd
import numpy as np
import config

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (pd.Timestamp, datetime.datetime, datetime.date)):
            return obj.isoformat()
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)

def get_session_folder():
    try:
        if current_app:
            return current_app.config.get('SESSION_FOLDER', config.SESSION_FOLDER)
    except RuntimeError:
        pass
    return config.SESSION_FOLDER

def load_session(session_id):
    path = os.path.join(get_session_folder(), f"{session_id}.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Error loading session JSON: {str(e)}")
    return None

def save_session(session_data):
    session_id = session_data['session_id']
    path = os.path.join(get_session_folder(), f"{session_id}.json")
    try:
        # Write-then-rename: a concurrent reader never sees a partial file.
        temp_path = f"{path}.{os.getpid()}.tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, cls=CustomJSONEncoder, indent=2, ensure_ascii=False)
        os.replace(temp_path, path)
    except Exception as e:
        logging.error(f"Error saving session JSON: {str(e)}")


def iter_session_files(session_folder=None):
    """Yield (session_id, path) for real session records only."""
    folder = session_folder or get_session_folder()
    if not os.path.isdir(folder):
        return
    for name in sorted(os.listdir(folder)):
        # `<id>.job.json` mirrors job state and is not a session record.
        if not name.endswith('.json') or name.endswith('.job.json'):
            continue
        yield name[:-len('.json')], os.path.join(folder, name)


def purge_old_sessions(session_folder, upload_folder, output_folder,
                       retention_days=0, max_sessions=0):
    """
    Delete sessions older than ``retention_days``, and trim to ``max_sessions``
    newest. Either limit set to 0 disables that rule.

    Uploads, cleaned files, chart PNGs, PDFs and the job mirror all go with the
    session record, so nothing is orphaned on disk.
    """
    if retention_days <= 0 and max_sessions <= 0:
        return 0

    records = []
    for session_id, path in iter_session_files(session_folder):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                data = json.load(handle)
            created = data.get("created_at") or ""
            records.append((created, session_id, path, data))
        except Exception:  # noqa: BLE001 - an unreadable record is a candidate too
            records.append(("", session_id, path, {}))

    records.sort(key=lambda item: item[0], reverse=True)

    doomed = []
    if retention_days > 0:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=retention_days)
        for record in records:
            try:
                if record[0] and datetime.datetime.fromisoformat(record[0]) < cutoff:
                    doomed.append(record)
            except ValueError:
                continue
    if max_sessions > 0 and len(records) > max_sessions:
        doomed.extend(records[max_sessions:])

    removed = 0
    for _, session_id, path, data in {r[1]: r for r in doomed}.values():
        try:
            for folder, filename in (
                (upload_folder, data.get("file_id")),
                (output_folder, data.get("cleaned_filename")),
                (output_folder, data.get("pdf_filename")),
            ):
                if filename:
                    target = os.path.join(folder, filename)
                    if os.path.exists(target):
                        os.remove(target)

            for index in range(20):  # chart PNGs written by the PDF renderer
                png = os.path.join(output_folder, f"{session_id}_chart_{index}.png")
                if os.path.exists(png):
                    os.remove(png)

            job_file = os.path.join(session_folder, f"{session_id}.job.json")
            if os.path.exists(job_file):
                os.remove(job_file)

            os.remove(path)
            removed += 1
        except OSError as exc:
            logging.warning(f"Retention sweep could not remove {session_id}: {exc}")

    if removed:
        logging.info(f"Retention sweep removed {removed} session(s).")
    return removed
