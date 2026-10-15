# Release Notes - Mercury (MP LCA Submission)

**Version Tag:** `v1.0.0` (Pre-release)  
**Branch:** `MP-LCA-submission`  
**Target Platform:** Python 3.10+ / Flask / SQLite WAL  
**Status:** Pre-release for Deployment  
**Security Notice:** Zero datasets, zero secrets, zero database artifacts included. Sample `.env.example` provided for configuration.

---

## 🌟 Executive Summary

**Mercury** is a production-grade, AI-assisted data wrangling, visualization, and diagnostics platform. It provides automated data hygiene analysis, conversational schema transformations, PowerBI-caliber statistical graphics, interactive data diffing, and executive-ready ReportLab PDF document compilation with strict security, rate limiting, and multi-tenant session isolation.

This submission package consolidates all features, architectural stability fixes, zero-CDN offline distributions, and security hardening into a verified release candidate.

---

## 🚀 Key Feature Highlights

### 1. Multi-Provider LLM Abstraction Layer
* **Unified Interface:** Built on LiteLLM with OpenAI-compatible client abstraction (`services/ai_service.py`), dynamically routing prompts across:
  * **Groq** (`groq/openai/gpt-oss-120b`, `llama-3.3-70b-versatile`) — *Default active provider*
  * **Google Gemini** (`gemini-2.5-flash`, `gemini-1.5-flash-latest`)
  * **OpenAI** (`gpt-4o-mini`, `gpt-4o`)
  * **Anthropic** (`claude-3-5-haiku-20241022`, `claude-3-7-sonnet`)
  * **NVIDIA NIM** (`meta/llama-3.3-70b-instruct`)
  * **Ollama** (Local self-hosted models, e.g. `llama3`)
* **Zero-Downtime Heuristic Fallback:** If remote AI providers experience outages (503 spikes, expired trial quotas, or 404 retired models), a local rule-based intent parser (`services/chat_service.py`) automatically intercepts and fulfills sort, drop, transform, and clean requests in `< 0.01s`.
* **Streaming SSE Chat:** Server-Sent Events stream assistant tokens in real-time while updating schema configurations dynamically.

### 2. High-Fidelity PowerBI-Grade Visualizations
* **Local Offline Chart.js:** Standalone bundled `static/chart.umd.min.js` completely eliminates CDN dependencies, firewall blocks, or offline failures.
* **11+ Visual Categories:** Interactive Area, Line, Bar, Column, Pie, Donut, Scatter, Histogram, Treemap (`squarify`), Waterfall, and Geospatial Map (`folium`).
* **Visual Pinning Workflow:** One-click "📌 Add to PDF Report" pins high-resolution base64 canvas graphics directly into the session's executive report queue.

### 3. Vectorized Data Cleaning & Transformation Engine
* **Pandas Execution Pipeline:** Strict type coercion, categorical mapping, regex text extraction, unit conversions, missing value handling, and duplicate elimination in `services/cleaning/executor.py`.
* **Outlier Detection:** Integrated Interquartile Range (IQR) and Z-score anomaly bounds.
* **15-Row Interactive Diff Preview:** Live Before (Original) vs. After (Cleaned) toggle with cell-level change highlighting, hover tooltips showing original values, and applied transformation audit cards.
* **Real-Time Cleaned Excel Sync:** Inline cell edits in the UI immediately update `cleaned_<session_id>.xlsx` using `openpyxl` with ASCII control-character sanitization (`safe_to_excel()`).

### 4. Executive PDF Diagnostics Report Compilation
* **ReportLab Document Engine:** Generates high-resolution diagnostic reports using typography from Google Lora serif fonts.
* **Dynamic Recompilation:** Editing data or pinning new visuals marks existing reports for re-compilation without session lockouts.
* **Asynchronous Worker Queue:** Report generation executes via bounded background workers (`ThreadPoolExecutor`), returning HTTP 202 with polling job tracking to prevent gateway timeouts.

### 5. Enterprise Security & Architecture Hardening
* **Authentication & Ownership:** SQLite-backed user accounts with secure password hashing, session ownership verification (`get_owned_session_or_404`), and stealth 404 responses on cross-tenant probes.
* **SSRF Defenses:** `utils/url_validator.py` resolves and blocks private/loopback IP addresses and cloud metadata services (`169.254.169.254`) for custom LLM endpoints.
* **Credential Redaction:** `APIKeyRedactionFilter` scrubs all API keys and Bearer tokens from server logs.
* **Upload Quota & Bomb Protection:** Magic byte inspection, 200MB size limits, max 10 Excel sheets, zip decompression bomb safeguards, and macro file rejection.
* **Maintenance Lifecycle:** Daemon cleanup scheduler automatically expires and deletes inactive session files after 24 hours (configurable TTL).

---

## 📦 Package Manifest & Structure

```
Mercury/
├── app.py                     # Flask application entrypoint & security middleware
├── config.py                  # Core path, quota, and environment configurations
├── requirements.txt           # Python dependency specifications
├── .env.example               # Environment variable templates
├── .gitignore                 # Optimized repository ignore rules
├── routes/                    # Modular Flask blueprints (auth, sessions, chat, viz, reports)
├── services/                  # Business logic (ai_service, dataset_service, report_service)
│   └── cleaning/              # Isolated data wrangling, validation, and intent parsing
├── models/                    # SQLAlchemy database entities (SQLite WAL)
├── repositories/              # Data access layer & background job trackers
├── powerbi_visuals/           # Matplotlib, Squarify, Seaborn & Folium visual engines
├── static/                    # Frontend UI assets (HTML, CSS, JS, Chart.js bundle)
├── utils/                     # Security guards (auth, SSRF, redaction, upload validator)
└── tests/                     # Automated pytest test suites
```

---

## 🛠️ Quickstart Guide

### 1. Environment Setup
```bash
# Clone the repository and switch to the release branch
git checkout MP-LCA-submission

# Create and activate a Python virtual environment
python -m venv .venv
.\.venv\Scripts\activate       # On Windows
# source .venv/bin/activate    # On Linux/macOS

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Copy `.env.example` to `.env` and specify preferred keys (optional; the app operates with offline local fallbacks):
```ini
SECRET_KEY=mercury-secure-production-key-change-me
LLM_PROVIDER=groq
LLM_MODEL=groq/openai/gpt-oss-120b
GROQ_API_KEY=your_groq_api_key_here
```

### 3. Launch Application
```bash
python app.py
```
Access the application in your browser at: **`http://127.0.0.1:5000`**

---

## 🧪 Verification & Health Checks

- **Server Status:** HTTP 200 OK at root endpoint `/`
- **Static Assets:** Bundled offline Chart.js verified at `/chart.umd.min.js`
- **Automated Tests:** Run complete regression test suite:
  ```bash
  pytest
  ```

---

## 👥 Authors & Acknowledgments

* **Project:** Mercury Data Science & Analytics Platform
* **Submission:** MP LCA Submission
* **Repository:** [https://github.com/diamond8874/Mercury](https://github.com/diamond8874/Mercury)
