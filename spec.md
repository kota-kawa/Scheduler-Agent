# Project Specifications & Guidelines

## 全体ルール (General Rules)
1. **機能等価性優先**: `app.py` 分割後も、HTTP API、HTML ルート、LLM ワークフロー、DB 書き込み結果、フロント表示を現状と同等に保つ。
2. **段階的移行**: いきなり全面移植しない。`app.py` を薄い互換レイヤーとして残し、内部実装を段階的に新モジュールへ移す。
3. **後方互換性維持**: 少なくとも移行完了まで、既存の `import app` 利用箇所（`asgi.py`、`mcp_server.py`、`scripts/migrate_sqlite_to_postgres.py`、`tests/*`）が壊れないこと。
4. **DB スキーマ非変更**: `SQLModel` のテーブル名・カラム名・型・既存制約は変更しない。
5. **エントリポイント非変更**: `asgi.py` / `Dockerfile` / `docker-compose.yml` の起動方式（`uvicorn asgi:app`）を維持。
6. **設定互換**: `DATABASE_URL`、`SESSION_SECRET`、`PROXY_PREFIX`、`SCHEDULER_MAX_ACTION_ROUNDS`、`SCHEDULER_MAX_SAME_READ_ACTION_STREAK` など既存環境変数の挙動を変えない。
7. **既存機能無影響（ゼロ回帰）**: 分割の目的は構造改善のみとし、既存機能の仕様・操作結果・レスポンス契約に影響を出さない。

## 対象機能一覧 (Feature Parity Checklist)

### 1) 公開 HTTP ルート（FastAPI）
以下のルートは **Path/Method/route name** を維持する。

| Method | Path | Route Name |
|---|---|---|
| GET | `/api/flash` | `api_flash` |
| GET | `/api/calendar` | `api_calendar` |
| GET | `/` | `index` |
| GET | `/agent-result` | `agent_result` |
| GET, POST | `/agent-result/day/{date_str}` | `agent_day_view` |
| GET | `/embed/calendar` | `embed_calendar` |
| GET | `/api/day/{date_str}` | `api_day_view` |
| GET, POST | `/day/{date_str}` | `day_view` |
| GET | `/api/routines/day/{weekday}` | `api_routines_by_day` |
| GET | `/api/routines` | `api_routines` |
| GET | `/routines` | `routines_list` |
| POST | `/routines/add` | `add_routine` |
| POST | `/routines/{id}/delete` | `delete_routine` |
| POST | `/routines/{id}/step/add` | `add_step` |
| POST | `/steps/{id}/delete` | `delete_step` |
| GET | `/api/models` | `list_models` |
| POST | `/model_settings` | `update_model_settings` |
| GET, DELETE | `/api/chat/history` | `manage_chat_history` |
| POST | `/api/chat` | `chat` |
| GET | `/evaluation` | `evaluation_page` |
| POST | `/api/evaluation/chat` | `evaluation_chat` |
| POST | `/api/evaluation/reset` | `evaluation_reset` |
| POST | `/api/evaluation/seed` | `evaluation_seed` |
| POST | `/api/evaluation/seed_period` | `evaluation_seed_period` |
| POST | `/api/add_sample_data` | `add_sample_data` |
| POST | `/api/evaluation/log` | `evaluation_log` |
| GET | `/api/evaluation/history` | `evaluation_history` |

### 2) 公開 Python シンボル互換
既存コードとテストが `app` モジュールの属性を直接参照しているため、移行中は次を `app.py` から再公開する。

- FastAPI/DB: `app`, `create_session`, `get_db`, `_init_db`, `Session`
- Models: `Routine`, `Step`, `DailyLog`, `CustomTask`, `DayLog`, `ChatHistory`, `EvaluationResult`
- Chat/Actions: `process_chat_request`, `_apply_actions`, `_run_scheduler_multi_step`, `_resolve_schedule_expression`, `_build_scheduler_context`, `_get_timeline_data`, `_build_final_reply`
- Trace helpers: `_attach_execution_trace_to_stored_content`, `_extract_execution_trace_from_stored_content`

### 3) DB テーブル互換
- `routine`, `step`, `daily_log`, `custom_task`, `day_log`, `chat_history`, `evaluation_result` は名称・列定義維持。
- `Base.metadata.create_all()` 相当の初期化タイミング（startup 時）を維持。

### 4) LLM 実行ロジックの互換
- マルチラウンド実行（重複防止、read-only 連続制限、execution trace 生成）の挙動を維持。
- `process_chat_request` の返却形式を維持: `reply`, `should_refresh`, `modified_ids`, `execution_trace`。

## 画面ルーティング (SPA Routes)
`templates/spa.html` + React の `data-page` 運用を維持する。

| URL | page_id | 主用途 |
|---|---|---|
| `/` | `index` | 通常カレンダー |
| `/day/{date}` | `day` | 通常日次ビュー |
| `/routines` | `routines` | ルーチン管理 |
| `/evaluation` | `evaluation` | 評価画面 |
| `/agent-result` | `agent-result` | エージェント結果カレンダー |
| `/agent-result/day/{date}` | `agent-day` | エージェント結果日次 |
| `/embed/calendar` | `embed-calendar` | 埋め込み表示 |

## API 契約 (API Contract - existing)

### 必須互換ポイント（テスト依存）
- `/api/day/{date_str}`: 不正日付は `400` + `{"detail":"Invalid date format"}`
- `/api/chat`: `messages` が list 以外なら `400` + `"messages must be a list"`
- `/api/chat`: 最終メッセージが `user` 以外なら `400` + `"last message must be from user"`
- `/model_settings`: `selection` が object 以外なら `400` + `"selection must be an object"`
- `/api/chat/history` GET: `execution_trace` を復元して返す
- `/api/chat/history` DELETE: `{"status":"cleared"}`

### 主要レスポンス形状（変更禁止）
- `/api/calendar`: `calendar_data`, `year`, `month`, `today`
- `/api/day/{date}`: `date`, `weekday`, `day_name`, `date_display`, `timeline_items`, `completion_rate`, `day_log_content`
- `/api/routines`: `{"routines": [...]}`
- `/api/routines/day/{weekday}`: `{"routines": [...]}`（step は時刻昇順）
- `/api/models`: `models`, `current(provider/model/base_url)`
- `/model_settings`: `status`, `applied(provider/model/base_url)`
- `/api/chat`: `reply`, `should_refresh`, `modified_ids`, `execution_trace`
- `/api/evaluation/chat`: `reply`, `raw_reply`, `actions`, `results`, `errors`, `execution_trace`

## 無影響保証 (Zero-Impact Gate)
以下をすべて満たした場合のみ「既存機能に影響なし」と判定する。

1. `spec.md` の公開ルート・API 契約・公開 Python シンボル互換をすべて維持。
2. 既存テストが全件パス（または従来通り skip）する。
3. 主要手動フロー（カレンダー、日次更新、ルーチン CRUD、チャット、評価画面）で差分がない。
4. DB スキーマ差分が 0（テーブル名/カラム/型/制約変更なし）。
5. 既存クライアント（`frontend`、`mcp_server.py`、`scripts/migrate_sqlite_to_postgres.py`）の呼び出し互換を維持。

## コーディング規約 (Coding Conventions)
1. **依存方向の固定**: `routers -> services -> (repositories/db/models)`、逆依存禁止。
2. **FastAPI 構成**: 各ドメインを `APIRouter` 化し、`create_app()` で `include_router()`。
3. **副作用最小化**: import 時に重い処理を実行しない。DB 初期化は startup ハンドラに限定。
4. **型ヒント維持**: 新規/移設関数は既存同等以上の型注釈を付与。
5. **関数分割基準**: 1関数が 120 行を超える場合は再分割検討。

## 命名規則 (Naming Conventions)
- パッケージ: `scheduler_agent`（snake_case）
- ルーター: `*_router.py`（例: `chat_router.py`）
- サービス: `*_service.py`（例: `action_service.py`）
- 互換レイヤー: ルート `app.py` は re-export のみを担当

## ディレクトリ構成方針 (Directory Structure Policy)
目標構成（最小案）:

```text
scheduler_agent/
  __init__.py
  application.py            # create_app(), app instance
  core/
    __init__.py
    config.py               # env/load_dotenv/定数
    db.py                   # engine/get_db/create_session/init
  models/
    __init__.py
    scheduler_models.py     # Routine, Step, DailyLog, CustomTask, DayLog
    chat_models.py          # ChatHistory, EvaluationResult
  web/
    __init__.py
    templates.py            # template_response, flash helpers
    routers/
      __init__.py
      page_router.py        # /, /day/{}, /agent-result*, /embed/calendar, /routines, /evaluation
      calendar_router.py    # /api/calendar
      day_router.py         # /api/day/{date}
      routines_router.py    # /api/routines*, /routines/*, /steps/*
      model_router.py       # /api/models, /model_settings
      chat_router.py        # /api/chat, /api/chat/history, /api/flash
      evaluation_router.py  # /api/evaluation/*, /api/add_sample_data
  services/
    __init__.py
    schedule_parser_service.py      # date/time 解析関連
    timeline_service.py             # _get_timeline_data, get_weekday_routines
    action_service.py               # _apply_actions
    chat_orchestration_service.py   # _run_scheduler_multi_step, process_chat_request
    reply_service.py                # _build_final_reply 系
    evaluation_seed_service.py      # _seed_evaluation_data, add_sample_data helper
```

互換レイヤー（`app.py`）要件:
- `from scheduler_agent.application import app` を公開。
- 既存テスト/スクリプトで直接参照されるモデル/関数を再エクスポート。
- 原則 200 行以内、ビジネスロジック禁止。

## エラーハンドリング方針 (Error Handling Policy)
1. DB 更新処理は service 単位で `commit`/`rollback` を明示する。
2. API 入力エラーは `HTTPException(400/404)` を継続利用。
3. 例外文言のうちテスト依存文字列は変更しない。
4. チャット履歴保存失敗時の挙動（処理継続 + ログ出力）を維持。
5. 互換上必要な内部制御エラーのフィルタリング（`_is_internal_system_error`）を維持。

## テスト方針 (Testing Policy)

### 最低実行
- `pytest tests/test_basic_api.py`
- `pytest tests/test_major_endpoints.py`
- `pytest tests/test_agent_result.py`
- `pytest tests/test_frontend_react.py`
- `pytest tests/test_app.py`（`TEST_DATABASE_URL` or `DATABASE_URL` を設定）

### 受け入れ条件
1. 既存テストがすべてパス（または既存同様に skip）
2. `/`・`/agent-result`・`/evaluation`・`/day/{date}` の表示崩れなし
3. チャット操作で `execution_trace` が保存・復元される
4. `mcp_server.py` 経由の `process_chat_request` 呼び出しが動作する
5. `scripts/migrate_sqlite_to_postgres.py` がモデル import エラーなく起動できる
6. `app.py` が責務集約点ではなく互換レイヤーになっている（新規ロジック禁止）
