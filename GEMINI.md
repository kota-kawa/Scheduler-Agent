# Project Context: Scheduler Agent

## Project Overview
**Scheduler Agent** is a Flask-based web application designed to help users manage their daily routines, custom tasks, and daily logs. It features a chat interface powered by Large Language Models (LLMs) that allows users to interact with their schedule using natural language (Japanese).

### Key Technologies
-   **Backend:** Python, Flask, SQLAlchemy (SQLite)
-   **LLM Integration:** OpenAI, Google Gemini, Anthropic Claude, Groq
-   **Frontend:** HTML (Jinja2), CSS, JavaScript (Vanilla)
-   **Containerization:** Docker, Docker Compose

### Core Functionality
-   **Routine Management:** Define recurring routines with specific steps and times.
-   **Day View:** Track progress on daily routine steps and custom tasks.
-   **Chat Interface:** Add tasks, toggle completion, and update logs via natural language conversation.
-   **Model Selection:** Dynamically switch between different LLM providers and models.

## Building and Running

### Prerequisites
-   Python 3.10+
-   Docker & Docker Compose (optional)

### Configuration
1.  **API Keys:** Create a `secrets.env` file in the project root (see `secrets.env` format in previous context or code).
    ```env
    OPENAI_API_KEY=sk-...
    GEMINI_API_KEY=AIza...
    # etc.
    ```

### Local Development
1.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
2.  **Initialize Database:**
    ```bash
    python -c "from app import app, db; app.app_context().push(); db.create_all()"
    ```
3.  **Run Application:**
    ```bash
    python app.py
    ```
    The app will be available at `http://localhost:5000`.

### Docker
1.  **Build and Run:**
    ```bash
    docker-compose up --build
    ```
    The app will be available at `http://localhost:5010` (mapped port).

## Development Conventions

### Architecture
-   **`app.py`:** The main Flask application file. It contains:
    -   **Database Models:** `Routine`, `Step`, `DailyLog`, `CustomTask`, `DayLog`.
    -   **Routes:** Web UI routes (`/`, `/day/<date>`, `/routines`) and API routes (`/api/chat`, `/api/models`).
    -   **Logic:** Helper functions for date parsing and applying LLM-generated actions (`_apply_actions`).
-   **`llm_client.py`:** Handles interactions with LLM providers.
    -   **`UnifiedClient`:** A provider-agnostic client that normalizes API calls to OpenAI, Anthropic, etc.
    -   **`call_scheduler_llm`:** Constructs the system prompt and parses the JSON response from the LLM.
-   **`model_selection.py`:** Manages available models and user selection logic. Shared logic pattern with other agents in the platform.

### LLM Interaction Protocol
-   The backend sends a structured system prompt defining the assistant's role and the available "actions" (JSON format).
-   The LLM is expected to return a JSON object containing a `reply` (text) and a list of `actions` (e.g., `create_custom_task`, `toggle_step`).
-   **`_extract_json_object`** in `llm_client.py` is used to robustly parse JSON from potentially markdown-wrapped responses.

### Frontend
-   **`static/scheduler.js`:** Handles the chat interface, sending messages to `/api/chat`, and fetching/updating model settings via `/api/models` and `/model_settings`.
-   **`templates/`:** Standard Jinja2 templates extending `layout.html`.

### Database
-   **SQLite:** stored in `instance/scheduler.db`.
-   **Schema:**
    -   `Routine` -> `Step` (One-to-Many)
    -   `DailyLog` links to `Step` for specific dates.
    -   `CustomTask` handles one-off tasks.
    -   `DayLog` stores free-text daily summaries.
