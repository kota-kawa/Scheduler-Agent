> 📝 一番下に日本語版もあります。

# Scheduler Agent 📅

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.128+-009688?logo=fastapi&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0+-D71F00?logo=sqlalchemy&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-blue?logo=postgresql&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.4-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-5.4-646CFF?logo=vite&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-API-412991?logo=openai&logoColor=white)
![Anthropic](https://img.shields.io/badge/Anthropic-Claude-D97706?logo=anthropic&logoColor=white)
![Google Gemini](https://img.shields.io/badge/Google-Gemini-4285F4?logo=google&logoColor=white)
![Groq](https://img.shields.io/badge/Groq-API-F55036?logoColor=white)

<img src="static/Scheduler-Agent-Logo.png" alt="Scheduler Agent Logo" width="800">

## UI Preview

<p align="center">
  <img src="assets/images/Scheduler-Agent-Screenshot.png" alt="Scheduler Agent Screenshot" width="1100">
</p>

## 🎬 Demo Videos

Click a thumbnail to open the video on YouTube.

| [![Demo Video 1](https://img.youtube.com/vi/FNXvN0xkqtU/hqdefault.jpg)](https://youtu.be/FNXvN0xkqtU) | [![Demo Video 2](https://img.youtube.com/vi/pMmqIU1zab8/hqdefault.jpg)](https://youtu.be/pMmqIU1zab8) | [![Demo Video 3](https://img.youtube.com/vi/SbBVq13BDxY/hqdefault.jpg)](https://youtu.be/SbBVq13BDxY) |
| --- | --- | --- |
| Schedule lunch for next Wednesday and Friday | Check next week's schedule, then create a gym routine for next Wednesday | Reschedule the gym routine to Saturday |

## Overview

Scheduler Agent is an AI-powered scheduling assistant that helps manage recurring routines, one-off tasks, and daily logs through a conversational chat interface backed by multiple LLM providers. Use the chat to add and modify tasks, toggle completion, and query your schedule; the UI lets you view and edit routines and logs.

## Welcome

**Scheduler Agent** is an AI-powered scheduling assistant that helps you manage routines and one-off tasks through a simple chat experience. Ask things like “What’s on my calendar tomorrow?” or “Add groceries next Tuesday,” and the assistant keeps your timeline organized.

## 🏗️ Architecture

```mermaid
flowchart LR
  user[User Browser] --> ui[React SPA / Jinja UI]
  ui --> api[FastAPI app.py]
  api --> orm[SQLAlchemy Models]
  orm --> db[(PostgreSQL)]
  api --> selector[model_selection.py]
  selector --> llm[llm_client.py]
  llm --> openai[OpenAI]
  llm --> claude[Anthropic Claude]
  llm --> gemini[Google Gemini]
  llm --> groq[Groq]
```

## 🧠 Design Decisions

- **Why FastAPI (instead of Flask):** async-ready request handling, automatic OpenAPI docs, and type-safe contracts with Pydantic/SQLModel help keep API evolution fast and predictable.
- **Why PostgreSQL + SQLAlchemy/SQLModel:** scheduling data has relational constraints (routines, steps, logs), so ACID guarantees and explicit schema migrations (Alembic) reduce data integrity risk.
- **Why signed-cookie sessions (not Redis yet):** current session usage is lightweight (flash/UI state), so Starlette `SessionMiddleware` minimizes infrastructure and operational overhead for single-instance deployments.
- **Why a multi-provider LLM routing layer:** provider abstraction in `model_selection.py`/`llm_client.py` avoids vendor lock-in and supports cost/latency optimization plus fallback options.
- **Why we added a dedicated calculation tool:** LLM-only reasoning is error-prone for date/weekday arithmetic, so deterministic tool execution handles those computations to reduce hallucination risk and improve production reliability. This design shows practical reliability engineering beyond prompt tuning.
- **Why React SPA + Vite with Jinja compatibility:** this enables fast, component-driven UI iteration while preserving simple server-rendered entry points where needed.

---

## 🚀 Quick start (Docker Compose only)

### 1) Prepare your API keys
Create a file named `secrets.env` in the project root and add the database settings plus at least one provider key.

```env
# secrets.env (example)
POSTGRES_PASSWORD=scheduler
POSTGRES_DB=scheduler
POSTGRES_USER=scheduler
DATABASE_URL=postgresql+psycopg2://scheduler:scheduler@db:5432/scheduler

OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
ANTHROPIC_API_KEY=sk-ant-...
# Prompt guard (recommended)
GROQ_API_KEY=gsk_...
# Monthly outbound LLM request cap (optional, default: 1000)
SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT=1000
# Max input length per user message (optional, default: 10000 chars)
SCHEDULER_MAX_INPUT_CHARS=10000
# Max output tokens per LLM call (optional, default: 5000)
SCHEDULER_MAX_OUTPUT_TOKENS=5000
```

### 2) Start the app
Run Docker Compose from the project root:

```bash
docker network create multi_agent_platform_net
```

```bash
docker compose up --build
```

### 3) Open the app
Once the logs settle, open the app in your browser:

👉 http://localhost:5010

### 4) Stop the app
When you’re done, stop the containers:

```bash
docker compose down
```

---

## 🗂️ Schema migrations (Alembic)

Schema changes are managed with Alembic.

```bash
export DATABASE_URL=postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler
alembic upgrade head
```

When you change SQLModel definitions, generate and apply a revision:

```bash
alembic revision --autogenerate -m "describe your schema change"
alembic upgrade head
```

---

## ✅ Testing and CI

### Local test run
Use the same Python version as CI (3.12+) and install dependencies.

```bash
python -m pip install -e .
python -m pip install pytest pytest-cov
```

Fast regression set:

```bash
pytest -q tests/test_architecture_imports.py tests/test_ci_smoke.py
```

PostgreSQL smoke + coverage:

```bash
export TEST_DATABASE_URL=postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler_test
export DATABASE_URL=$TEST_DATABASE_URL
export SESSION_SECRET=test-secret
pytest -q \
  --cov=scheduler_agent \
  --cov=app \
  --cov-report=term-missing \
  --cov-report=xml \
  tests/test_architecture_imports.py \
  tests/test_ci_smoke.py \
  tests/test_ci_postgres_smoke.py
```

### CI behavior
- `.github/workflows/syntax-check.yml` runs Python and TypeScript syntax checks.
- `.github/workflows/tests.yml` runs:
  - fast tests (`test_architecture_imports`, `test_ci_smoke`)
  - PostgreSQL-backed smoke tests (`test_ci_postgres_smoke`)
  - coverage report generation (`reports/coverage.xml`)
  - skipped-test detection (CI fails if any test is skipped in integration job)

---

## 📜 License

This project is released under the [MIT License](LICENSE.md).

---

<details>
<summary>日本語版（クリックして開く）</summary>

## 👋 はじめに

### UI Preview

<p align="center">
  <img src="assets/images/Scheduler-Agent-Screenshot.png" alt="Scheduler Agent スクリーンショット" width="1100">
</p>

## 🎬 デモ動画

サムネイルをクリックするとYouTubeで開きます。

| [![デモ動画 1](https://img.youtube.com/vi/FNXvN0xkqtU/hqdefault.jpg)](https://youtu.be/FNXvN0xkqtU) | [![デモ動画 2](https://img.youtube.com/vi/pMmqIU1zab8/hqdefault.jpg)](https://youtu.be/pMmqIU1zab8) | [![デモ動画 3](https://img.youtube.com/vi/SbBVq13BDxY/hqdefault.jpg)](https://youtu.be/SbBVq13BDxY) |
| --- | --- | --- |
| 来週の水曜日と金曜日にランチの予定を入れる | 来週の予定を確認した後、来週水曜日にジムに行くルーティンを作成する | ジムに行くルーティンを土曜日に変更する |

## 概要

Scheduler Agent は、会話型チャットインターフェースを通じてルーティンや単発タスク、日次ログを管理するためのAIアシスタントです。チャットでタスクを追加・編集したり、完了を切り替えたり、予定を確認でき、UIでルーティンやログを閲覧・編集できます。

**Scheduler Agent** は、チャットで予定やタスクを管理できるAIスケジュールアシスタントです。
「明日の予定は？」「来週火曜に買い物を追加して」など、話しかけるだけでタイムラインを整理できます。

## 🏗️ アーキテクチャ

```mermaid
flowchart LR
  user[ユーザーのブラウザ] --> ui[React SPA / Jinja UI]
  ui --> api[FastAPI app.py]
  api --> orm[SQLAlchemy モデル]
  orm --> db[(PostgreSQL)]
  api --> selector[model_selection.py]
  selector --> llm[llm_client.py]
  llm --> openai[OpenAI]
  llm --> claude[Anthropic Claude]
  llm --> gemini[Google Gemini]
  llm --> groq[Groq]
```

## 🧠 技術的な意思決定（Design Decisions）

- **FastAPI を選んだ理由（Flask ではなく）:** 非同期処理に素直に対応でき、OpenAPI ドキュメントを自動生成できるため、型安全な API 契約を保ちながら機能追加を速く進められるためです。
- **PostgreSQL + SQLAlchemy/SQLModel を選んだ理由:** ルーティン・ステップ・ログのように関係性を持つデータを扱うため、ACID 特性と Alembic による明示的なマイグレーション運用で整合性リスクを抑えやすいからです。
- **Redis ではなく署名付き Cookie セッションを使う理由（現時点）:** セッション用途がフラッシュメッセージなど軽量な UI 状態中心のため、`SessionMiddleware` でインフラ構成を増やさず運用コストを低く保てるからです。
- **マルチ LLM ルーティング層を置く理由:** `model_selection.py` / `llm_client.py` でプロバイダ依存を分離し、ベンダーロックイン回避・コスト/レイテンシ最適化・フォールバック戦略を取りやすくするためです。
- **計算ツールを用意した理由:** 曜日・日付計算は LLM 単体推論だと誤りが出やすいため、決定的なツール実行に切り出して計算ミスとハルシネーションのリスクを下げ、運用の安定性を高めるためです。これはプロンプト調整だけに頼らない実践的な信頼性設計です。
- **React SPA + Vite と Jinja 互換構成を併用する理由:** コンポーネント単位で UI を高速に改善しつつ、必要な箇所ではシンプルなサーバーサイド入口を維持できるためです。

---

## 🚀 すぐに始める（Docker Composeのみ）

### 1) APIキーの準備
プロジェクト直下に `secrets.env` を作成し、DB設定と少なくとも1つのキーを追加してください。

```env
# secrets.env の例
POSTGRES_PASSWORD=scheduler
POSTGRES_DB=scheduler
POSTGRES_USER=scheduler
DATABASE_URL=postgresql+psycopg2://scheduler:scheduler@db:5432/scheduler

OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
ANTHROPIC_API_KEY=sk-ant-...
# プロンプトガード（推奨）
GROQ_API_KEY=gsk_...
# 月次LLM APIリクエスト上限（任意、未設定時は1000）
SCHEDULER_MONTHLY_LLM_REQUEST_LIMIT=1000
# 1メッセージあたり入力文字数上限（任意、未設定時は10000）
SCHEDULER_MAX_INPUT_CHARS=10000
# 1回のLLM呼び出しあたり出力トークン上限（任意、未設定時は5000）
SCHEDULER_MAX_OUTPUT_TOKENS=5000
```

### 2) 起動
プロジェクト直下で次のコマンドを実行します。

```bash
docker network create multi_agent_platform_net
```

```bash
docker compose up --build
```

### 3) ブラウザでアクセス
ログが落ち着いたら、以下へアクセスしてください。

👉 http://localhost:5010

### 4) 停止
終了するときは、次のコマンドで停止します。

```bash
docker compose down
```

---

## 🗂️ スキーママイグレーション（Alembic）

スキーマ変更は Alembic で管理します。

```bash
export DATABASE_URL=postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler
alembic upgrade head
```

SQLModel の定義を変更した場合は、リビジョンを作成して適用してください。

```bash
alembic revision --autogenerate -m "スキーマ変更の内容"
alembic upgrade head
```

---

## ✅ テストとCI

### ローカルでのテスト実行
CI と同じ Python 3.12+ を使い、依存を入れてください。

```bash
python -m pip install -e .
python -m pip install pytest pytest-cov
```

軽量な回帰テスト:

```bash
pytest -q tests/test_architecture_imports.py tests/test_ci_smoke.py
```

PostgreSQL スモークテストとカバレッジ:

```bash
export TEST_DATABASE_URL=postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler_test
export DATABASE_URL=$TEST_DATABASE_URL
export SESSION_SECRET=test-secret
pytest -q \
  --cov=scheduler_agent \
  --cov=app \
  --cov-report=term-missing \
  --cov-report=xml \
  tests/test_architecture_imports.py \
  tests/test_ci_smoke.py \
  tests/test_ci_postgres_smoke.py
```

### CI の動作
- `.github/workflows/syntax-check.yml` で Python / TypeScript の構文チェックを実行します。
- `.github/workflows/tests.yml` で以下を実行します。
  - fast テスト（`test_architecture_imports`, `test_ci_smoke`）
  - PostgreSQL 連携スモークテスト（`test_ci_postgres_smoke`）
  - カバレッジレポート生成（`reports/coverage.xml`）
  - skip 監視（integration ジョブで skip が1件でもあれば失敗）

---

## 📜 ライセンス

本プロジェクトは [MIT License](LICENSE.md) で公開されています。

</details>
