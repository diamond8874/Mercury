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
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload size

# Ensure necessary directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(SESSION_FOLDER, exist_ok=True)
