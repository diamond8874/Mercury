# Mercury - AI Data Cleaning MVP

Mercury is a Flask-based web application that provides intelligent data ingestion, schema analysis, and AI-driven data cleaning recommendations. It leverages an asynchronous processing architecture and integrates with OpenAI-compatible APIs (configured for Nvidia endpoints) to help users clean, transform, and understand their datasets, ultimately generating comprehensive PDF reports.

## Key Features
- **Data Ingestion:** Upload `.csv`, `.xls`, or `.xlsx` datasets.
- **Schema Analysis:** Automatically parses dataset structure, detects missing values, and evaluates unique value distributions.
- **AI-Assisted Cleaning:** Provides recommendations on dropping useless identifiers, imputing missing values, and formatting columns for downstream machine learning tasks.
- **Asynchronous Processing:** Long-running data processing jobs are handled safely in background threads, maintaining a responsive UI.
- **Interactive Chat Interface:** Refine and negotiate data cleaning steps dynamically with the AI via a chat interface.
- **PDF Reporting:** Generates downloadable reports summarizing the cleaning steps and outcomes.

## Getting Started

### Prerequisites
- Python 3.9+
- An API Key compatible with the OpenAI spec (currently configured to point to Nvidia's endpoint).

### Installation
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set your environment variables (create a `.env` file in the root directory):
   ```ini
   NVIDIA_API_KEY=your_api_key_here
   ```
3. Run the application:
   ```bash
   python app.py
   ```
4. Access the application in your browser at `http://127.0.0.1:5000`.

## Testing
To test the platform's cleaning capabilities, you can generate a sample dirty dataset by running:
```bash
python generate_test_data.py
```
This will produce a `test_dirty_data.xlsx` file that you can upload to the application.

## Developer & Agent Documentation
This repository is configured for autonomous multi-agent development. If you are a contributing agent or developer, you **MUST** review the following documentation before making code changes:

- **[AGENTS.md](./AGENTS.md):** Governance, token constraints, and execution safety rules.
- **[ARCHITECTURE.md](./ARCHITECTURE.md):** High-level system overview and directory map.
- **[KNOWLEDGE_GRAPH.md](./KNOWLEDGE_GRAPH.md):** Complete structural index of modules, functions, and interfaces. Read this file instead of scanning full source files.
- **[COMMIT.md](./COMMIT.md):** Guidelines for Conventional Commits and branch naming.
- **[CHANGELOG.md](./CHANGELOG.md) & [COMMIT_LOG.md](./COMMIT_LOG.md):** Mandatory tracking logs for codebase changes.
