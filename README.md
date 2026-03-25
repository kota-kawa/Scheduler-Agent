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
![CI](https://github.com/kota-kawa/Scheduler-Agent/actions/workflows/tests.yml/badge.svg)

<img src="static/Scheduler-Agent-Logo.png" alt="Scheduler Agent Logo" width="800">

## UI Preview

<p align="center">
  <img src="assets/images/Scheduler-Agent-Screenshot.png" alt="Scheduler Agent Screenshot" width="1100">
</p>

## 🎬 Demo Videos

Click a thumbnail to open the video on YouTube!

| [![Demo Video 1](https://img.youtube.com/vi/FNXvN0xkqtU/hqdefault.jpg)](https://youtu.be/FNXvN0xkqtU) | [![Demo Video 2](https://img.youtube.com/vi/pMmqIU1zab8/hqdefault.jpg)](https://youtu.be/pMmqIU1zab8) | [![Demo Video 3](https://img.youtube.com/vi/SbBVq13BDxY/hqdefault.jpg)](https://youtu.be/SbBVq13BDxY) |
| --- | --- | --- |
| Schedule lunch for next Wednesday and Friday | Check next week's schedule, then create a gym routine for next Wednesday | Reschedule the gym routine to Saturday |

## Overview

**Scheduler Agent** is an AI-powered scheduling assistant that manages recurring routines, one-off tasks, and daily logs through a conversational chat interface. Ask things like “What’s on my calendar tomorrow?” or “Add groceries next Tuesday,” and the assistant keeps your timeline organized. Multiple LLM providers are supported, and the UI lets you view and edit routines and logs directly.

## 🎯 What This Project Demonstrates

- **Full-stack development**: Async FastAPI backend + React/TypeScript SPA + PostgreSQL, all wired together end-to-end
- **LLM integration**: Multi-provider routing with a clean abstraction layer (OpenAI / Anthropic / Gemini / Groq) to avoid vendor lock-in
- **Reliability engineering**: Deterministic tool execution for date/weekday arithmetic, preventing hallucinations at a design level rather than relying solely on prompt tuning
- **Production readiness**: CI/CD pipeline (GitHub Actions), schema migrations (Alembic), rate limiting, input sanitization, and prompt injection defense
- **Security awareness**: Trusted-host enforcement, signed-cookie sessions, HTTPS-only flag, per-user request caps, and guest data TTL cleanup
- **Empirical evaluation**: Benchmark-driven model comparison across 9 LLM providers with structured failure analysis

## ✨ Features

- Conversational task management — add, edit, delete, and complete tasks via natural language
- Recurring routine builder with named steps and per-step durations
- Multi-LLM backend — switch models per request at runtime
- Daily log viewer queryable by date (“Show me last Friday’s log”)
- Prompt injection defense and input length/output token caps
- Guest session support with automatic TTL-based data cleanup
- One-command Docker Compose deploy

## 🏗️ Architecture

<p align="center">
  <img src="assets/images/scheduler-agent-architecture.png" alt="Scheduler Agent Architecture" width="900">
</p>

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

## 🧪 Evaluation

### Scheduler Agent

**Role**
The Scheduler Agent manages tasks, routines, memos, and date-dependent operations through natural-language interaction and tool calling.

**Evaluation Protocol**
Ten task-management scenarios were evaluated. Each task was tested three times and scored as:
- **○**: All 3 attempts succeeded
- **△**: 1–2 attempts succeeded
- **×**: All 3 attempts failed

The 10 evaluation tasks:

| # | Task |
|---|------|
| 1 | Add a task called "Buy detergent" |
| 2 | Show my schedule from tomorrow through the day after tomorrow |
| 3 | Rename "Buy detergent" to "Buy fabric softener" |
| 4 | Mark "Buy fabric softener" as complete |
| 5 | Schedule a "Dentist" appointment starting at 15:30 tomorrow |
| 6 | Delete "Buy fabric softener", and add a note "Don't forget insurance card" to the "Dentist" task |
| 7 | Create a new routine called "Workout" — I'll do it on Mondays and Thursdays |
| 8 | Add a step "Squats" (10 min) to the "Workout" routine just created |
| 9 | Also do the "Workout" routine on Saturdays |
| 10 | Show me last Friday's daily log |

**Results**

| Task | GPT-5.1 | Gemini 3 Pro | Claude Opus 4.5 | Claude Haiku 4.5 | Llama 3.3 70B | Qwen3 32B | Gemini 2.5 Flash Lite | Llama 3.1 8B | GPT-OSS 20B |
|:----:|:-------:|:------------:|:---------------:|:----------------:|:-------------:|:---------:|:---------------------:|:------------:|:-----------:|
| 1  | ○ | ○ | ○ | ○ | ○ | ○ | × | ○ | ○ |
| 2  | ○ | ○ | ○ | ○ | ○ | ○ | × | ○ | ○ |
| 3  | ○ | ○ | ○ | ○ | ○ | ○ | × | △ | ○ |
| 4  | ○ | ○ | ○ | × | ○ | ○ | × | ○ | ○ |
| 5  | ○ | ○ | ○ | ○ | ○ | ○ | × | △ | ○ |
| 6  | ○ | ○ | ○ | × | ○ | ○ | × | ○ | × |
| 7  | ○ | ○ | ○ | × | ○ | ○ | △ | ○ | ○ |
| 8  | ○ | ○ | ○ | × | ○ | ○ | × | ○ | ○ |
| 9  | ○ | ○ | ○ | × | × | ○ | × | △ | ○ |
| 10 | × | ○ | ○ | ○ | × | ○ | △ | × | × |

**Failure Analysis**

| Model | Main Failure Cause |
|-------|--------------------|
| **GPT-5.1** | Date calculation error on task 10: evaluated on Tuesday Dec 9 2025, it identified "last Friday" as Nov 28 instead of Dec 5. Day-of-week recognition was correct, but cross-week arithmetic was off. |
| **Claude Haiku 4.5** | Tasks 4, 6, 7, 8, 9 — no tool calls were made at all; the model responded with plain text only (No tool calls). |
| **Llama 3.3 70B** | Task 9: wrote Sunday instead of Saturday. Task 10: date off by one day (Dec 6 instead of Dec 5). |
| **Gemini 2.5 Flash Lite** | Widespread failures across most tasks. Likely over-applied the system-prompt rule "no JSON in user-facing responses" to tool-call JSON generation as well, treating tool invocation as a prohibited action. |
| **Llama 3.1 8B** | Tasks 3 and 5: garbled Japanese strings appeared in generated arguments (e.g., "演溪角を起ん"), likely due to tokenizer or training-data coverage gaps for Japanese. Task 10: date calculation error. |
| **GPT-OSS 20B** | Task 6: only executed the deletion, ignoring the "add a note" instruction. Task 10: large date calculation error (referenced Dec 2). |
| **Qwen3 32B** | **No failures.** Despite being a "standard-tier" model, it answered all 10 tasks correctly, showing strong suitability for structured scheduler operations. |

**Key Takeaway**
For structured tool-use tasks like this scheduler, **model suitability is not determined by general model prestige alone**. A mid-tier model (Qwen3 32B) outperformed several frontier models by reliably translating natural-language instructions into correct tool calls.

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
GROQ_API_KEY=gsk_...
```

### 2) Start the app
Run Docker Compose from the project root:

```bash
docker network create multi_agent_platform_net
```

```bash
docker compose up --build
```

> Security note: the default `docker-compose.yml` no longer publishes PostgreSQL to host ports. Keep DB access internal to the Compose network for public deployments.

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

---

## ✅ Testing, CI/CD

### Local test run
Use the same Python version as CI (3.12+) and install dependencies.

```bash
python -m pip install -e .
python -m pip install pytest pytest-cov
```

```bash
pytest -q tests/test_architecture_imports.py tests/test_ci_smoke.py
```

### CI/CD behavior

GitHub Actions runs syntax checks, fast tests, PostgreSQL smoke tests, and coverage reporting in sequence — then auto-deploys to the server on `main` push via SSH.

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

**Scheduler Agent** は、会話型チャットを通じてルーティン・単発タスク・日次ログを管理するAIスケジュールアシスタントです。「明日の予定は？」「来週火曜に買い物を追加して」と話しかけるだけでタイムラインを整理でき、UIでルーティンやログを直接閲覧・編集することもできます。複数のLLMプロバイダに対応しています。

## 🎯 このプロジェクトで示していること

- **フルスタック開発**: 非同期 FastAPI バックエンド + React/TypeScript SPA + PostgreSQL をエンドツーエンドで構築
- **LLM統合**: OpenAI / Anthropic / Gemini / Groq をクリーンな抽象化レイヤーでルーティングし、ベンダーロックインを回避
- **信頼性設計**: 日付・曜日計算を決定的なツール実行に切り出し、プロンプト調整に頼らない設計レベルでのハルシネーション対策
- **プロダクション対応**: CI/CD（GitHub Actions）・スキーママイグレーション（Alembic）・レートリミット・入力サニタイズ・プロンプトインジェクション対策
- **セキュリティ意識**: 信頼ホスト検証・署名付き Cookie セッション・HTTPS 強制・ユーザーごとのリクエスト上限・ゲストデータ TTL 自動削除
- **実験的評価**: 9つのLLMプロバイダを構造化ベンチマークで比較し、失敗要因を分析

## ✨ 機能一覧

- 自然言語によるタスク管理（追加・編集・削除・完了切り替え）
- 名前付きステップと所要時間を持つ繰り返しルーティンの作成
- リクエストごとにモデルを切り替えられるマルチLLMバックエンド
- 日付指定で過去ログを確認（「先週金曜の日報を見せて」など）
- プロンプトインジェクション防御・入力文字数/出力トークン上限
- ゲストセッション対応（TTLによるデータ自動クリーンアップ）
- Docker Compose によるワンコマンドデプロイ

## 🏗️ アーキテクチャ

<p align="center">
  <img src="assets/images/scheduler-agent-architecture.png" alt="Scheduler Agent アーキテクチャ" width="900">
</p>

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

## 🧪 評価

### Scheduler Agent

**役割**
Scheduler Agent は、自然言語の対話とツール呼び出しを通じて、タスク・ルーティン・メモ・日付依存の操作を管理します。

**評価プロトコル**
10件のタスク管理シナリオを評価しました。各タスクは3回試行し、以下の基準でスコアリングしました。

- **○**: 3回全て成功
- **△**: 1〜2回成功
- **×**: 全て失敗

評価タスク一覧:

| # | タスク内容 |
|---|-----------|
| 1 | 「洗剤を買う」というタスクを追加して |
| 2 | 明日から明後日までの予定を教えて |
| 3 | 「洗剤を買う」を「柔軟剤を買う」に名前を変えて |
| 4 | 「柔軟剤を買う」タスク，完了した |
| 5 | 明日の15:30分から「歯医者」の予定を入れて |
| 6 | 「柔軟剤を買う」は削除して，「歯医者」のタスクに「保険証を忘れない」というメモを追加して |
| 7 | 「筋トレ」という新しいルーティンを作って．月曜と木曜にやるよ |
| 8 | さっき作った「筋トレ」ルーティンに，「スクワット」というステップ（10分）を追加して |
| 9 | 「筋トレ」ルーティン，土曜日もやることにする |
| 10 | 先週の金曜日の日報を見せて |

**評価結果**

| タスク | GPT-5.1 | Gemini 3 Pro | Claude Opus 4.5 | Claude Haiku 4.5 | Llama 3.3 70B | Qwen3 32B | Gemini 2.5 Flash Lite | Llama 3.1 8B | GPT-OSS 20B |
|:------:|:-------:|:------------:|:---------------:|:----------------:|:-------------:|:---------:|:---------------------:|:------------:|:-----------:|
| 1  | ○ | ○ | ○ | ○ | ○ | ○ | × | ○ | ○ |
| 2  | ○ | ○ | ○ | ○ | ○ | ○ | × | ○ | ○ |
| 3  | ○ | ○ | ○ | ○ | ○ | ○ | × | △ | ○ |
| 4  | ○ | ○ | ○ | × | ○ | ○ | × | ○ | ○ |
| 5  | ○ | ○ | ○ | ○ | ○ | ○ | × | △ | ○ |
| 6  | ○ | ○ | ○ | × | ○ | ○ | × | ○ | × |
| 7  | ○ | ○ | ○ | × | ○ | ○ | △ | ○ | ○ |
| 8  | ○ | ○ | ○ | × | ○ | ○ | × | ○ | ○ |
| 9  | ○ | ○ | ○ | × | × | ○ | × | △ | ○ |
| 10 | × | ○ | ○ | ○ | × | ○ | △ | × | × |

**各モデルの主な失敗要因**

| モデル | 主な失敗要因 |
|--------|------------|
| **GPT-5.1** | タスク10で日付計算ミス。検証日（2025年12月9日・火曜日）に対し，「先週の金曜日」を11月28日と誤認（正解は12月5日）。曜日の認識は正しいが，週を跨ぐ計算で誤りが生じた。 |
| **Claude Haiku 4.5** | タスク4, 6, 7, 8, 9でツール呼び出し（JSON生成）が行われず，テキスト応答のみとなるケースが多発した（No tool calls）。 |
| **Llama 3.3 70B** | タスク9で曜日指定を誤り（土曜→日曜），タスク10では日付を1日ずれて計算（12月6日）。 |
| **Gemini 2.5 Flash Lite** | 全体的にツール呼び出しのためのJSON生成ができず失敗が多かった。システムプロンプトの「ユーザー向け応答でのJSON出力禁止」という制約を，ツール呼び出しにおけるJSON生成にまで拡大解釈したと考えられる。 |
| **Llama 3.1 8B** | タスク3・5で日本語引数に意味不明な文字列（「演溪角を起ん」等）が混入。トークナイザまたは学習データの日本語カバレッジの問題と考えられる。タスク10でも日付計算ミス。 |
| **GPT-OSS 20B** | タスク6で複合指示（削除＋メモ追加）の片方（削除のみ）しか実行しない傾向。タスク10では大幅に日付を誤った（12月2日を参照）。 |
| **Qwen3 32B** | **失敗なし。** 「普通」クラスのモデルでありながら全タスクに正解し，スケジューラー操作への高い適性を示した。 |

**この結果が示すこと**
**構造化されたツール利用タスクにおいて，モデルの適性は一般的な知名度だけでは決まらない**という重要な知見を示しています。Qwen3 32B は標準的なモデルでありながら，複数のフロンティアモデルを上回る安定性を見せました。

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

---

## ✅ テストとCI/CD

### ローカルでのテスト実行
CI と同じ Python 3.12+ を使い、依存を入れてください。

```bash
python -m pip install -e .
python -m pip install pytest pytest-cov
```

```bash
pytest -q tests/test_architecture_imports.py tests/test_ci_smoke.py
```

### CI/CD の動作

GitHub Actions で構文チェック・fast テスト・PostgreSQL スモークテスト・カバレッジ計測を順に実行し、`main` への push 時のみ SSH 経由でサーバへ自動デプロイします。

---

## 📜 ライセンス

本プロジェクトは [MIT License](LICENSE.md) で公開されています。

</details>
