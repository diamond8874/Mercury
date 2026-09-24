import os
import shutil
import pytest
from app import app
import config
from utils.auth import init_db, create_user
from models import init_db as init_sqlalchemy_db

@pytest.fixture
def client(tmp_path):
    app.config['TESTING'] = True
    test_upload = str(tmp_path / 'test_uploads')
    test_output = str(tmp_path / 'test_output_data')
    test_session = str(tmp_path / 'test_sessions')
    test_db = str(tmp_path / 'test_users.db')

    os.makedirs(test_upload, exist_ok=True)
    os.makedirs(test_output, exist_ok=True)
    os.makedirs(test_session, exist_ok=True)

    orig_upload = config.UPLOAD_FOLDER
    orig_output = config.OUTPUT_FOLDER
    orig_session = config.SESSION_FOLDER
    orig_db = config.DATABASE_PATH

    app.config['UPLOAD_FOLDER'] = test_upload
    app.config['OUTPUT_FOLDER'] = test_output
    app.config['SESSION_FOLDER'] = test_session
    app.config['DATABASE_PATH'] = test_db

    config.UPLOAD_FOLDER = test_upload
    config.OUTPUT_FOLDER = test_output
    config.SESSION_FOLDER = test_session
    config.DATABASE_PATH = test_db

    with app.app_context():
        init_db(test_db)
        init_sqlalchemy_db(test_db)  # Create/migrate all SQLAlchemy tables including jobs
        create_user("testadmin", "password123", db_path=test_db)

    with app.test_client() as test_client:
        # Pre-authenticate test client with session cookie
        login_resp = test_client.post('/api/auth/login', json={"username": "testadmin", "password": "password123"})
        assert login_resp.status_code == 200
        yield test_client

    config.UPLOAD_FOLDER = orig_upload
    config.OUTPUT_FOLDER = orig_output
    config.SESSION_FOLDER = orig_session
    config.DATABASE_PATH = orig_db

@pytest.fixture
def unauthenticated_client(tmp_path):
    app.config['TESTING'] = True
    test_upload = str(tmp_path / 'unauth_uploads')
    test_output = str(tmp_path / 'unauth_output_data')
    test_session = str(tmp_path / 'unauth_sessions')
    test_db = str(tmp_path / 'unauth_users.db')

    os.makedirs(test_upload, exist_ok=True)
    os.makedirs(test_output, exist_ok=True)
    os.makedirs(test_session, exist_ok=True)

    orig_upload = config.UPLOAD_FOLDER
    orig_output = config.OUTPUT_FOLDER
    orig_session = config.SESSION_FOLDER
    orig_db = config.DATABASE_PATH

    app.config['UPLOAD_FOLDER'] = test_upload
    app.config['OUTPUT_FOLDER'] = test_output
    app.config['SESSION_FOLDER'] = test_session
    app.config['DATABASE_PATH'] = test_db

    config.UPLOAD_FOLDER = test_upload
    config.OUTPUT_FOLDER = test_output
    config.SESSION_FOLDER = test_session
    config.DATABASE_PATH = test_db

    with app.app_context():
        init_db(test_db)
        init_sqlalchemy_db(test_db)  # Create/migrate all SQLAlchemy tables

    with app.test_client() as test_client:
        yield test_client

    config.UPLOAD_FOLDER = orig_upload
    config.OUTPUT_FOLDER = orig_output
    config.SESSION_FOLDER = orig_session
    config.DATABASE_PATH = orig_db

