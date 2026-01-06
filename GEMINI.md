# Project Context: Scheduler Agent

## Project Overview
**Scheduler Agent** is a FastAPI-based web application designed to help users manage their daily routines, custom tasks, and daily logs. It features a chat interface powered by Large Language Models (LLMs) that allows users to interact with their schedule using natural language (Japanese).

### Key Technologies
-   **Backend:** Python, FastAPI, SQLAlchemy (PostgreSQL)
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
2.  **Run Application:**
    ```bash
    uvicorn app:app --reload --port 5000
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
-   **`app.py`:** The main FastAPI application file. It contains:
    -   **Database Models:** `Routine`, `Step`, `DailyLog`, `CustomTask`, `DayLog`.
    -   **Routes:** Web UI routes (`/`, `/day/<date>`, `/routines`) and API routes (`/api/chat`, `/api/models`).
    -   **Logic:** Helper functions for date parsing and applying LLM-generated actions (`_apply_actions`).
-   **`llm_client.py`:** Handles interactions with LLM providers.
    -   **`UnifiedClient`:** A provider-agnostic client that normalizes API calls to OpenAI, Anthropic, etc.
    -   **`call_scheduler_llm`:** Builds the tool-calling prompt and reads tool calls from the LLM response instead of parsing ad-hoc JSON.
-   **`model_selection.py`:** Manages available models and user selection logic. Shared logic pattern with other agents in the platform.

### LLM Interaction Protocol
-   The backend sends a structured system prompt defining the assistant's role and registers tools (function calling) for each supported action.
-   The LLM is expected to emit tool calls (e.g., `create_custom_task`, `toggle_step`) and a natural-language `reply` alongside them—no custom JSON parsing required.

### Frontend
-   **`static/scheduler.js`:** Handles the chat interface, sending messages to `/api/chat`, and fetching/updating model settings via `/api/models` and `/model_settings`.
-   **`templates/`:** Standard Jinja2 templates extending `layout.html`.

### Database
-   **PostgreSQL:** configured via `DATABASE_URL`.
-   **Schema:**
    -   `Routine` -> `Step` (One-to-Many)
    -   `DailyLog` links to `Step` for specific dates.
    -   `CustomTask` handles one-off tasks.
    -   `DayLog` stores free-text daily summaries.

## Critical Instruction / 重要指示
どれだけ時間とコストをかけてもよいので、確実に目標が達成されるようにしてほしい。
