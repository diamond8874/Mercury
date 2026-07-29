import logging
from flask import Flask
import config
from components.routes import api_blueprint
from utils.fonts import download_lora_fonts

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Flask app
app = Flask(__name__, static_folder='static', static_url_path='')

# Apply configuration settings
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = config.OUTPUT_FOLDER
app.config['SESSION_FOLDER'] = config.SESSION_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH

# Register Blueprints
app.register_blueprint(api_blueprint)

if __name__ == '__main__':
    logging.info("Starting Flask application...")
    # Load fonts in background
    download_lora_fonts()
    app.run(host='0.0.0.0', port=5000, debug=True)
