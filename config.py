import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Directory Configurations
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')
OUTPUT_FOLDER = os.path.join(os.getcwd(), 'output_data')
SESSION_FOLDER = os.path.join(os.getcwd(), 'sessions')

# File Upload Restrictions
ALLOWED_EXTENSIONS = {'xlsx', 'xls', 'csv'}
MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 200 * 1024 * 1024))  # 200MB max upload size

# Database Configuration
DATABASE_PATH = os.environ.get('DATABASE_PATH', os.path.join(os.getcwd(), 'users.db'))

# ---------------------------------------------------------------------------
# 4D: Upload content-validation caps (also read by utils/upload_validator.py)
# ---------------------------------------------------------------------------
MAX_ROWS: int = int(os.environ.get("MAX_ROWS", 200_000))
MAX_COLS: int = int(os.environ.get("MAX_COLS", 500))
MAX_XLSX_SHEETS: int = int(os.environ.get("MAX_XLSX_SHEETS", 10))
MAX_UNCOMPRESSED_BYTES: int = int(
    os.environ.get("MAX_UNCOMPRESSED_BYTES", 500 * 1024 * 1024)  # 500 MB guard
)

# 4D: Per-user quotas
MAX_SESSIONS_PER_USER: int = int(os.environ.get("MAX_SESSIONS_PER_USER", 20))
MAX_STORAGE_BYTES_PER_USER: int = int(
    os.environ.get("MAX_STORAGE_BYTES_PER_USER", 1024 * 1024 * 1024)  # 1 GB
)

# 4D: Cleanup / TTL
SESSION_TTL_SECONDS: int = int(os.environ.get("SESSION_TTL_SECONDS", 86_400))    # 24 h
CLEANUP_INTERVAL_SECONDS: int = int(os.environ.get("CLEANUP_INTERVAL_SECONDS", 3_600))  # 1 h

# Ensure necessary directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(SESSION_FOLDER, exist_ok=True)
