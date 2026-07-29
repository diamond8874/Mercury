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
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, cls=CustomJSONEncoder, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Error saving session JSON: {str(e)}")
