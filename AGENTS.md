# Repository Guidelines

## Project Structure & Module Organization
- `app.py` hosts the Flask app, SQLAlchemy models (Routine, Step, DailyLog, CustomTask, DayLog), HTML routes, and JSON endpoints used by the chat UI.
- LLM integration and model routing live in `llm_client.py` and `model_selection.py`; these read provider/API key overrides from environment variables or `model_settings.json` (via `MULTI_AGENT_SETTINGS_PATH`).
- UI assets sit in `templates/` (Jinja templates) and `static/` (`scheduler.js`, `style.css`). Local SQLite data resides in `instance/scheduler.db` for development only.
- Container entrypoints are defined by `Dockerfile` and `docker-compose.yml` (service `web`).

## Build, Test, and Development Commands
- Create a venv and install deps: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.
- Run locally: `export FLASK_APP=app.py FLASK_DEBUG=1` then `flask run` (or `python app.py`) and open http://localhost:5000.
- Containerized run: `docker compose up --build web` (binds 5010->5000).
- Configure LLM access with env vars (e.g., `OPENAI_API_KEY`, `GEMINI_API_KEY`, `CLAUDE_API_KEY`, `GROQ_API_KEY`) and optional `MULTI_AGENT_SETTINGS_PATH` pointing to shared model settings.

## Coding Style & Naming Conventions
- Python: follow PEP 8 with 4-space indent, snake_case functions, PascalCase models, and type hints where practical (see `llm_client.py`). Keep helpers small and log-friendly errors.
- Templates: prefer extending `templates/layout.html` and keep logic minimal inside Jinja blocks.
- JavaScript: camelCase utilities, keep fetch error handling consistent with `static/scheduler.js`; avoid inline script tags when adding new interactions.

## Testing Guidelines
- There is no automated suite yet; before opening a PR, run the dev server and exercise: calendar navigation, routine/step CRUD, custom task toggles, chat responses, and model selector updates.
- If adding tests, colocate Flask/SQLAlchemy unit tests under `tests/` (create it) and use pytest-style names (`test_*.py`) with factories for in-memory SQLite.

## Commit & Pull Request Guidelines
- Git history is not present here; use concise, imperative commit subjects (e.g., `Add routine timeline metrics`) and include a short body when touching configs or data models.
- PRs should describe behavior changes, impacted env vars/secrets, and any DB or schema implications (currently none beyond `db.create_all()`). Add screenshots/GIFs for UI changes and list manual checks performed (e.g., `flask run`, `docker compose up`).

## Security & Configuration Tips
- Do not commit real API keys or personal data; keep secrets in environment variables or a local `secrets.env` that stays untracked. Rotate any leaked keys immediately.
- The bundled SQLite database is for local use; avoid checking in new populated copies, and clear it before sharing if it contains user data.

## Critical Instruction / 重要指示
どれだけ時間とコストをかけてもよいので、確実に目標が達成されるようにしてほしい。
