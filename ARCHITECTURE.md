# System Overview & Architecture

## Architecture
This project is a Flask-based web application with asynchronous background processing capabilities and AI integration (OpenAI/Nvidia endpoint). It is designed to handle data uploads, schema analysis, data cleaning/processing, and PDF report generation.

- **Frontend:** HTML, CSS, JavaScript (in `static/` directory).
- **Backend:** Flask web server (`app.py`), serving REST API endpoints.
- **Data Processing:** Pandas and Numpy for dataset handling.
- **AI Integration:** OpenAI API client configured to use an Nvidia endpoint.
- **Reporting:** ReportLab for generating PDF documents.
- **Background Jobs:** Handled via Python `threading` and in-memory state tracking.

## Directory Map
- `/`: Project root containing the main application and scripts.
  - `app.py`: Main Flask application, API endpoints, background job management, AI integration logic.
  - `generate_test_data.py`: Script to generate a synthetic dirty dataset for testing.
  - `requirements.txt`: Python dependencies.
- `static/`: Frontend assets.
  - `index.html`: Main entry point for the web interface.
  - `app.js`: Client-side logic for the application.
  - `style.css`: Stylesheet.
- `uploads/`: Directory for storing user-uploaded files (Excel/CSV).
- `output_data/`: Directory for storing processed files and reports.
- `sessions/`: Directory for storing local session data in JSON format.
- `fonts/`: Directory for storing downloaded fonts used in PDF generation.
