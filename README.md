# Scheduler-Agent

<img src="static/Scheduler-Agent-Logo.png" alt="Scheduler Agent Logo" width="800">


## 概要
Scheduler-Agent は、日次ルーチンとカスタムタスクを 1 つのタイムラインで可視化し、LLM チャットや MCP (Model Context Protocol) ツール経由で自然言語操作できる FastAPI アプリです。ブラウザ UI / IoT-Agent / 外部エージェントが同じバックエンド API・DB を共有する設計になっています。

**English**
Scheduler-Agent is a FastAPI app that unifies daily routines and custom tasks into one timeline and lets you manipulate them via natural-language LLM chat or the Model Context Protocol. The browser UI, IoT-Agent, and external agents all share the same backend APIs and database.

## 主な特徴
- **ルーチン & タイムライン**: `Routine`/`Step` モデルで曜日ごとの定型作業を管理し、`DailyLog`/`DayLog` 連動の完了率・メモを表示。
- **カスタムタスク**: その日の ad-hoc 予定 (`CustomTask`) を追加・編集・完了チェックし、PostgreSQL に保存。
- **LLM チャット UI**: `UnifiedClient` が OpenAI/Claude/Gemini/Groq を抽象化し、`scheduler_tools.py` の Function Calling を実行。
- **モデルセレクター**: `/api/models` から候補を取得し、`model_selection.py` で provider/model/base_url を切替。
- **MCP サーバー**: `asgi.py` + `mcp_server.py` が SSE 経由で `manage_schedule` ツールを提供。
- **Docker/ASGI 対応**: FastAPI/Starlette で `/mcp` を提供し、`uvicorn` や `docker compose` で運用可能。

**English**
- **Routines & timeline:** `Routine`/`Step` models manage weekday workflows while `DailyLog`/`DayLog` supply completion rates and notes.
- **Custom tasks:** `CustomTask` entries cover ad-hoc schedules with full CRUD and PostgreSQL persistence.
- **LLM chat UI:** `UnifiedClient` abstracts OpenAI/Claude/Gemini/Groq and invokes `scheduler_tools.py` functions.
- **Model selector:** `/api/models` feeds UI options; `model_selection.py` switches provider/model/base_url overrides.
- **MCP server:** `asgi.py` + `mcp_server.py` expose the `manage_schedule` tool over SSE.
- **Docker/ASGI ready:** FastAPI/Starlette serves the UI and MCP transport so you can run via `uvicorn` or `docker compose`.

## 技術スタック
- FastAPI / Starlette / Uvicorn (HTML/JSON ルート、ASGI & MCP トランスポート)
- SQLAlchemy (PostgreSQL)
- PostgreSQL
- Vanilla JS + Jinja2 (`templates/`, `static/`)
- OpenAI / Anthropic / Google Gemini / Groq SDK

**English**
- FastAPI / Starlette / Uvicorn for views, APIs, and MCP transport
- SQLAlchemy models (PostgreSQL)
- PostgreSQL
- Vanilla JS + Jinja2 (`templates/`, `static/`)
- OpenAI / Anthropic / Google Gemini / Groq SDKs

## リポジトリ構成
```
.
├── app.py                # FastAPI アプリ/モデル/HTML+JSON ルート
├── asgi.py               # FastAPI + SSE ルーター
├── mcp_server.py         # MCP Server (`manage_schedule`)
├── scheduler_tools.py    # LLM Function Calling ツール群
├── llm_client.py         # UnifiedClient & ツール解析
├── model_selection.py    # モデル選択ロジック
├── templates/            # Jinja テンプレート
├── static/               # `scheduler.js`, `style.css`
├── Dockerfile            # uvicorn エントリーポイント
├── docker-compose.yml    # service "web" (5010)
└── requirements.txt      # 依存関係
```

**English**
```
.
├── app.py                # FastAPI app, models, HTML+JSON routes
├── asgi.py               # FastAPI + SSE router
├── mcp_server.py         # MCP server (`manage_schedule`)
├── scheduler_tools.py    # LLM function-calling toolset
├── llm_client.py         # UnifiedClient + tool parsing
├── model_selection.py    # Model selection logic
├── templates/            # Jinja templates
├── static/               # `scheduler.js`, `style.css`
├── Dockerfile            # uvicorn entrypoint
├── docker-compose.yml    # `web` service (5010)
└── requirements.txt      # Dependencies
```

## 前提条件
- Python 3.10 以上
- PostgreSQL 14 以上 (ローカルまたは Docker)
- (任意) Docker / Docker Compose v2
- OpenAI / Anthropic / Google / Groq いずれかの API キー

**English**
- Python 3.10+
- PostgreSQL 14+ (local or Docker)
- Optional: Docker / Docker Compose v2
- At least one API key for OpenAI, Anthropic, Google, or Groq

## セットアップ手順
1. 依存をインストール:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. `secrets.env` に API キーやベース URL を記入 (`app.py` が自動で読み込みます)。
3. PostgreSQL を起動し、`DATABASE_URL` を設定します (例: `postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler`)。DB がなければ作成してください。

**English**
1. Install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Add API keys/base URLs to `secrets.env` (loaded automatically by `app.py`).
3. Start PostgreSQL and set `DATABASE_URL` (example: `postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler`). Create the database if it does not exist.

## ローカル実行
- **FastAPI Dev Server**
  ```bash
  export DATABASE_URL=postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler
  uvicorn app:app --reload --port 5000
  ```
  ブラウザで http://localhost:5000 を開きます。

- **ASGI / MCP サーバー**
  ```bash
  uvicorn asgi:app --reload --port 5010
  ```
  `/mcp` に SSE エンドポイント、`/` に UI が提供されます。

**English**
- **FastAPI dev server**
  ```bash
  export DATABASE_URL=postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler
  uvicorn app:app --reload --port 5000
  ```
  Visit http://localhost:5000.

- **ASGI / MCP server**
  ```bash
  uvicorn asgi:app --reload --port 5010
  ```
  SSE endpoints live under `/mcp`, while the UI stays at `/`.

## Docker / Compose
```
docker compose up --build
```
- `web` と `db` を起動し、PostgreSQL (5432) と UI (5010) を公開します。`MULTI_AGENT_NETWORK` があればそのネットワークへ参加して `scheduler-agent` エイリアスを持ちます。
- `docker-compose.yml` の既定 DB ユーザー/パスワードは `scheduler` です。必要に応じて変更してください。

**English**
```
docker compose up --build
```
- Starts `web` + `db`, exposes PostgreSQL (5432) and the UI (5010), and joins the `MULTI_AGENT_NETWORK` (if present) with the alias `scheduler-agent`.
- Default DB credentials in `docker-compose.yml` are `scheduler` / `scheduler`; change them if needed.

## 主な環境変数 (日本語)
| 変数 | 用途 | 必須 | デフォルト |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` / `CLAUDE_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` | UnifiedClient で各プロバイダに接続 | いずれか 1 つ必須 | なし |
| `OPENAI_BASE_URL`, `CLAUDE_API_BASE`, `GEMINI_API_BASE`, `GROQ_API_BASE` | カスタムエンドポイント設定 | 任意 | provider ごとのデフォルト |
| `MULTI_AGENT_SETTINGS_PATH` | `model_settings.json` の絶対パス上書き | 任意 | `../Multi-Agent-Platform/model_settings.json` |
| `DATABASE_URL` | DB 接続文字列 | 必須 | `postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler` |
| `PROXY_PREFIX` ほか | リバースプロキシ下でのパス調整 | 任意 | 空文字 |

**Key Environment Variables (English)**
| Variable | Purpose | Required | Default |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` / `CLAUDE_API_KEY` / `GEMINI_API_KEY` / `GROQ_API_KEY` | Provider credentials for UnifiedClient | Any one | None |
| `OPENAI_BASE_URL`, `CLAUDE_API_BASE`, `GEMINI_API_BASE`, `GROQ_API_BASE` | Custom API endpoints | Optional | Provider defaults |
| `MULTI_AGENT_SETTINGS_PATH` | Override path to `model_settings.json` | Optional | `../Multi-Agent-Platform/model_settings.json` |
| `DATABASE_URL` | Database URL | Required | `postgresql+psycopg2://scheduler:scheduler@localhost:5432/scheduler` |
| `PROXY_PREFIX`, etc. | Adjust UI paths behind reverse proxies | Optional | Empty |

## データベースメモ
- PostgreSQL を前提に運用します。開発/検証/本番で DB を分ける場合は `DATABASE_URL` を切り替えてください。
- `DailyLog` / `CustomTask` / `DayLog` が増えると容量が膨らむため、バックアップや定期メンテナンスを推奨します。

**English**
- PostgreSQL is the primary datastore. Use different `DATABASE_URL` values for dev/staging/prod.
- As `DailyLog`, `CustomTask`, and `DayLog` grow, plan for backups and periodic maintenance.

## チャット & MCP 連携
- `/api/chat` 系エンドポイントが UI からの問い合わせを受け、`scheduler_tools.py` のツールを順次起動。
- MCP では `mcp_server.py` の `manage_schedule` ツールが `process_chat_request()` を共有し、ブラウザと同じレスポンスを返します。
- `static/scheduler.js` はモデル選択 UI とチャットフォームで fetch エラーや MIME を厳密に検証し、失敗時にユーザーへ通知します。

**English**
- `/api/chat` endpoints process UI chat input and trigger the tools defined in `scheduler_tools.py`.
- The MCP `manage_schedule` tool in `mcp_server.py` reuses `process_chat_request()`, so external agents get identical responses.
- `static/scheduler.js` validates fetch responses (status + MIME) for the model selector and chat form, surfacing errors to users.

## 手動テストチェックリスト
- ルーチン/ステップ CRUD + 曜日フィルタが正しく反映されるか
- タイムライン完了チェックやメモが PostgreSQL に保存されるか
- カスタムタスクの追加/削除/時刻変更が UI とチャット双方で動作するか
- `/api/models` → UI セレクター → `/model_settings` 更新が連動するか
- チャット履歴読み込み/リセット、LLM 応答、ツールログが表示されるか
- MCP (`/mcp/sse`, `/mcp/messages`) 経由の `manage_schedule` が応答するか

**Manual Test Checklist (English)**
- Verify routine/step CRUD plus weekday filters update the timeline.
- Confirm timeline completion toggles and memos persist to PostgreSQL.
- Add/delete/retime custom tasks from both UI and chat flows.
- Check `/api/models` populates the selector and `/model_settings` updates after switching.
- Ensure chat history load/reset, LLM replies, and tool call logs show correctly.
- Exercise MCP endpoints (`/mcp/sse`, `/mcp/messages`) and confirm `manage_schedule` responds.

## トラブルシュート
- **API キー未設定**: `UnifiedClient` 初期化で例外が出るので `secrets.env` を確認。
- **モデル設定エラー**: `MULTI_AGENT_SETTINGS_PATH` が壊れている場合はデフォルト (Groq GPT-OSS) にフォールバック。
- **PostgreSQL 接続エラー**: `DATABASE_URL`、ユーザー/パスワード、DB 作成状況を確認。
- **MCP SSE 404**: 逆プロキシ配下では `SCRIPT_NAME`（`proxy_prefix`）が正しく渡っているか確認。

**Troubleshooting (English)**
- **Missing API keys:** `UnifiedClient` will throw; populate `secrets.env` with the required keys.
- **Broken model settings:** Invalid `MULTI_AGENT_SETTINGS_PATH` JSON falls back to the Groq GPT-OSS default.
- **PostgreSQL connection errors:** Verify `DATABASE_URL`, credentials, and that the database exists.
- **MCP SSE 404:** Ensure `SCRIPT_NAME`/`proxy_prefix` is forwarded correctly when behind a reverse proxy.

貢献する際は、上記の手動テストを実施し、PR では挙動差分・環境変数変更点・UI スクリーンショットを共有してください。

**English**
When contributing, run the manual checks above and include behavior changes, env var impacts, and UI screenshots in your PR.

## ライセンス / License
このプロジェクトは MIT ライセンスの下で公開されています。詳細は [LICENSE.md](LICENSE.md) をご覧ください。

This project is licensed under the MIT License - see the [LICENSE.md](LICENSE.md) file for details.
