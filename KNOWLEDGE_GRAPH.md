# Knowledge Graph - Mercury Multi-Provider LLM Abstraction

This file serves as a lightweight structural index of the repository to minimize token consumption during context loading. It defines the current architecture, data flow, modules, and environment matrices for the multi-provider LLM system.

---

## 🗺️ Multi-Provider LLM Architecture & Data Flow

Mercury uses a clean, decoupled **Adapter/Factory Pattern** to resolve, configure, and route LLM calls across multiple providers including **OpenAI, Anthropic (Claude), Google (Gemini), Ollama, OpenRouter, and Nvidia**.

```
[ Frontend: Settings UI / Chat / Schema ]
                   │
                   ▼ (HTTP JSON Payload)
   [ Flask routes: routes.py ]
                   │
                   ▼ (get_llm_client)
 [ UnifiedLLMClient: services/ai_service.py ]
                   │
                   ├─► Auto-resolves Provider & Model Name
                   ├─► Maps proper API Keys & Base URLs
                   │
                   ▼ (Completion Interface)
        [ LiteLLM Engine Wrapper ]
                   │
  ┌────────────────┼────────────────┬────────────────┐
  ▼                ▼                ▼                ▼
[OpenAI]      [Anthropic]        [Gemini]        [Ollama/Local]
```

### Key Components:
1. **Frontend Settings Panel (`static/index.html` & `static/app.js`)**: Allows users to select an LLM Provider, select/type an LLM Model, override the API Key, or provide a Custom Base URL. These settings are persisted in `localStorage` and sent with every API request.
2. **REST API Endpoints (`components/routes.py`)**: Endpoints `/api/analyze`, `/api/sessions/<id>/chat`, and `/api/sessions/<id>/chat/stream` parse the frontend's LLM configuration parameters and pass them to the backend client creator.
3. **Unified LLM Client (`services/ai_service.py`)**: Standardizes prompt formatting, system messages, streaming responses, and error handling. It utilizes LiteLLM to communicate with diverse AI providers while exposing an OpenAI-compatible interface (`client.chat.completions.create(...)`).

---

## 📦 Module & Dependency Map

| File/Module | Type | Description | Dependencies |
|-------------|------|-------------|--------------|
| `app.py` | Flask Entrypoint | Lean main entry point for booting and initializing the Flask application. | `flask`, `config`, `components.routes`, `utils.fonts` |
| `config.py` | Configuration | Defines folder paths, extension restrictions, and loads environment variables. | `os`, `dotenv` |
| `components/routes.py` | Blueprint Routes | Refactored routes parsing custom LLM states (provider, model, keys) for schema analysis, streaming chat sessions, `/api/sessions/<id>/update_cell`, `/api/sessions/<id>/dry_run`, `/api/sessions/<id>/custom_chart`, `/api/sessions/<id>/pin_chart`, and customized PDF compilation. | `flask`, `pandas`, `numpy`, `matplotlib`, `reportlab`, `services`, `utils` |
| `services/ai_service.py` | Service | Contains `UnifiedLLMClient` implementing multi-provider LLM routing, auto-resolving, LiteLLM compatibility, and OpenAI base URL routing for Nvidia (`https://integrate.api.nvidia.com/v1`). | `litellm`, `os`, `logging` |
| `services/data_service.py` | Service | Core data operations, `apply_column_transformation` engine delegating to `services.cleaning`, schema summary, mock suggestions, and background worker threads. | `pandas`, `numpy`, `os`, `logging`, `utils`, `services.cleaning` |
| `services/cleaning/` | Subpackage | Safe, modular AI cleaning engine featuring `operation_registry.py` (central op definitions & dtype targets), `intent_parser.py` (Natural Human Language → structured plan conversion for shorthand & natural phrasings like `0 to No`, `0->No`, `transform column X into Y`, `convert float`, `fill missing 0`), `validator.py` (pre-execution validation), `executor.py` (isolated handlers), `audit.py` (structured audit logs). | `pandas`, `numpy`, `re`, `difflib`, `logging` |
| `utils/helpers.py` | Utility Helper | Functions for filename validation and JSON response parsing. | `json`, `config` |
| `utils/session_manager.py` | Session Manager | Manages JSON session persistence, thread-safe memory caching (`SESSION_CACHE`), path-traversal sanitization (`sanitize_session_id`), and exponential backoff file locking (`SESSION_LOCK`). | `json`, `os`, `threading`, `re` |
| `powerbi_visuals/trend_charts.py` | Trend Charts Visualizer | Generates line, area, column, and combo charts with thread safety (`PLOT_LOCK`) and high DPI (`dpi=200`) image rendering. | `matplotlib`, `pandas`, `threading` |
| `powerbi_visuals/geo_charts.py` | Geo Charts Visualizer | Generates interactive bubble and choropleth maps with NaN radius safeguards. | `folium`, `pandas` |
| `utils/fonts.py` | PDF Font Utility | Core downloader and registrar for PDF report fonts. | `os`, `urllib`, `reportlab` |
| `utils/job_tracker.py` | Job Tracking Utility | Thread-safe tracking and polling of background cleaning jobs. | `threading` |
| `generate_test_data.py` | Script | Generates a synthetic dataset for testing data cleaning capabilities. | `pandas`, `numpy`, `random` |
| `tests/test_cleaning_engine.py` | Test Suite | Comprehensive unit tests for intent parsing, validation, execution safety, datatype conversions, and realistic NL prompts (26 test cases). | `pytest`, `pandas`, `numpy`, `services.cleaning` |
| `static/app.js` | Frontend JS | Handles dynamic settings state storage (`localStorage`), settings modal save handlers, `contentEditable` interactive cell editing in data preview table, and sends custom LLM parameters in API requests. | None |
| `static/index.html` | Frontend UI | Re-architected settings panel enabling selection of LLM Providers (OpenAI, Anthropic, Gemini, Ollama, OpenRouter, Nvidia) and Model names. | `static/style.css`, `static/app.js` |


---

## ⚙️ Environment Matrix

The LLM abstraction dynamically routes API calls. It checks settings sent from the UI setting overrides first, then falls back to environment variables.

| Environment Variable | Provider Target | Usage / Description |
|----------------------|-----------------|---------------------|
| `NVIDIA_API_KEY` | NVIDIA | Default API Key used for Nvidia endpoints (e.g. `meta/llama-3.3-70b-instruct`). |
| `OPENAI_API_KEY` | OpenAI | API Key for authenticating with official OpenAI models (e.g. `gpt-4o`). |
| `ANTHROPIC_API_KEY` | Anthropic | API Key for authenticating with Anthropic Claude models (e.g. `claude-3-7-sonnet`). |
| `GEMINI_API_KEY` | Google Gemini | API key for authenticating with Google Gemini models (e.g. `gemini-2.5-flash`). |
| `OPENROUTER_API_KEY` | OpenRouter | API key for routing requests through OpenRouter. |
| `OLLAMA_BASE_URL` | Ollama (Local) | Custom local base URL (defaults to `http://localhost:11434`). |
| `LLM_PROVIDER` | System Default | Default provider to use if none is selected in the UI (e.g., `nvidia`, `openai`). |
| `LLM_MODEL` | System Default | Default model to use if none is specified (defaults to `meta/llama-3.3-70b-instruct`). |
