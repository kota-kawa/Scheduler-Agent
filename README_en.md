# Scheduler Agent 📅

[日本語](README.md)

<img src="static/Scheduler-Agent-Logo.png" alt="Scheduler Agent Logo" width="800">

## 👋 Introduction

Welcome to **Scheduler-Agent**!
This is an AI-powered schedule management assistant designed to make your daily life a little more convenient.

"What is my schedule for tomorrow?" "Add items to the shopping list for next Tuesday."
Just chat naturally, and the AI will organize your schedule for you.
Manage your daily routines and sudden tasks in a single, easy-to-read timeline! ✨

## ✨ Features

*   **📅 Timeline View**
    Display daily routines and specific tasks for the day in chronological order. Understand "what to do now" at a glance.

*   **💬 Easy Chat Operation**
    No complex operations required. Just talk to the AI like you would in a messaging app to add or check your schedule.

*   **🤖 Smart AI Assistant**
    Powered by the latest AI models like OpenAI (GPT), Google (Gemini), and Anthropic (Claude). You can even switch between AI models to suit your preference.

---

## 🚀 Quick Start (Recommended)

If you have **Docker** installed on your computer, you can start using it immediately.

### 1. 🔑 Preparation: Set up AI Keys (API Keys)
First, set up your **API Keys**, which are your passport to the AI.
Create a file named `secrets.env` in the project folder and write down the keys you have.

```env
# Content of secrets.env file (Example)
# At least one key is required!

OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. ▶️ Start: Run one command
Enter the following magic command in your terminal.

```bash
docker compose up --build
```

### 3. 🌐 Access: Open your browser
Once the text stops flowing, you are ready!
Click the link below to meet your assistant.

👉 [http://localhost:5010](http://localhost:5010)

---

## 🛠️ For Developers (Local Execution)

If you want to run it directly using Python, look here.
We use the fast tool **uv**, so the setup is lightning fast ⚡️

### 1. 📦 Install uv
If you haven't installed it yet, get it here!

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 🏗️ Create Environment
Install all necessary libraries with a single command.

```bash
uv sync
```

### 3. 🗄️ Database Setup
A PostgreSQL database is required.
Run it locally and write the connection information in `secrets.env`.

```env
# Example
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/scheduler
```

#### Legacy SQLite migration (optional)
The app now targets PostgreSQL only. If you already have `instance/scheduler.db`, run:

```bash
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/scheduler \\
  python scripts/migrate_sqlite_to_postgres.py
```

Use `--force` to truncate the PostgreSQL tables before import.

### 4. 🎨 Frontend (Vite)
The frontend is built with Vite. Node.js is required.

```bash
npm install
npm run build
```

For hot reload during development, start the Vite dev server in another terminal (API is proxied to port 5000).

```bash
npm run dev
```

The Vite dev server is available at [http://localhost:5173](http://localhost:5173).

### 5. ▶️ Start
Let's start it up!

```bash
uv run uvicorn app:app --reload --port 5000
```
Once started, access [http://localhost:5000](http://localhost:5000).

---

## 📜 License

This project is released under the [MIT License](LICENSE.md).
Feel free to modify it and create your own strongest assistant! 🛠️
