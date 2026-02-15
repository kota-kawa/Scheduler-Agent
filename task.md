# Current Task Context

## 今回やること・目的 (Goal/Objective)
`app.py`（約 3000 行）を責務ごとに分割し、保守性・テスト容易性を改善する。
ただし「機能追加」ではなく、**既存仕様を維持した内部構造改善**を目的とする。
既存機能に影響を出さないことを最上位条件とする。

## やること (Must)

### Phase 0: 事前固定（回帰防止）
- [ ] 現行の API/ルート/公開シンボルの一覧を固定する（`spec.md` の契約を基準化）。
- [ ] 既存テストを実行し、ベースライン結果を保存する。
- [ ] `app.py` 以外からの依存 (`mcp_server.py`, `asgi.py`, `scripts/*`, `tests/*`) を明示する。
- [ ] 既存機能無影響（Zero-Impact Gate）の判定項目を先に固定する。

### Phase 1: 新パッケージ骨格の作成
- [ ] `scheduler_agent/` パッケージと `core/`, `models/`, `services/`, `web/routers/` を作成する。
- [ ] `scheduler_agent/application.py` に `create_app()` と `app` を作成する。
- [ ] middleware / static mount / template 設定を移設する。

### Phase 2: DB とモデルの分離
- [ ] `core/db.py` に engine 初期化、`get_db`, `create_session`, startup 初期化を移す。
- [ ] `models/*` に SQLModel 群を移し、テーブル名と定義を維持する。
- [ ] `app.py` からモデルを再公開し、既存 import 互換を保つ。

### Phase 3: ヘルパー・サービス分離
- [ ] 日時解析系（`_resolve_schedule_expression` 周辺）を `services/schedule_parser_service.py` へ移す。
- [ ] タイムライン集計・ルーチン取得を `services/timeline_service.py` へ移す。
- [ ] アクション適用（`_apply_actions`）を `services/action_service.py` へ移す。
- [ ] チャット実行制御（`_run_scheduler_multi_step`, `process_chat_request`）を `services/chat_orchestration_service.py` へ移す。
- [ ] 最終返信生成（`_build_final_reply` 系）を `services/reply_service.py` へ移す。

### Phase 4: Router 化
- [ ] ページ系ルートを `web/routers/page_router.py` へ集約。
- [ ] API を `calendar/day/routines/model/chat/evaluation` 単位で Router 分割。
- [ ] route path / method / route name を完全一致で維持。

### Phase 5: 互換レイヤー化
- [ ] ルート直下 `app.py` を薄い re-export 層へ置換する。
- [ ] `mcp_server.py` とテストが期待する公開シンボルを `app.py` から参照可能に保つ。
- [ ] `asgi.py` 側の import (`from app import app`) を変更せず動作させる。

### Phase 6: 検証と仕上げ
- [ ] テストを実行し、回帰がないことを確認する。
- [ ] 手動確認（カレンダー遷移、day 更新、ルーチン CRUD、チャット、評価画面）を実施する。
- [ ] `app.py` が実質的に集約ロジックを持たないことを最終確認する。
- [ ] Zero-Impact Gate（仕様/API/シンボル/DB/主要フロー）を全項目 PASS させる。

## やらないこと (Non-goals)
<!-- 今回のスコープ外のこと -->
- [ ] 新機能の追加や UI の大幅な再設計（機能パリティ優先）
- [ ] バックエンドのビジネスロジック/DB スキーマの変更（必要最小限の API 追加は別途合意）
- [ ] LLM モデルやプロバイダの変更、推論ロジックの改変
- [ ] パフォーマンス最適化の大規模施策（移行後の別タスク）

## 受け入れ基準 (Acceptance Criteria)
- [ ] 既存機能に影響が出ていないことを Zero-Impact Gate で確認済み。
- [ ] `spec.md` の「公開 HTTP ルート」と「API 契約」の互換を満たす。
- [ ] `app.py` の責務が互換レイヤー中心になっている（目安: 200 行前後、ロジック最小）。
- [ ] `pytest tests/test_basic_api.py` がパスする。
- [ ] `pytest tests/test_major_endpoints.py` がパスする。
- [ ] `pytest tests/test_agent_result.py` がパスする。
- [ ] `pytest tests/test_frontend_react.py` がパスする。
- [ ] DB 利用可能環境で `pytest tests/test_app.py` がパスする。
- [ ] `mcp_server.py` の `process_chat_request` 呼び出しが動作する。
- [ ] `scripts/migrate_sqlite_to_postgres.py` がモデル import に失敗しない。

## Zero-Impact Gate (無影響判定)
- [ ] ルート互換: Path/Method/route name が全一致。
- [ ] API 互換: 必須レスポンスキーとエラー文言が一致。
- [ ] Python シンボル互換: `app` モジュールの公開属性が既存呼び出しと互換。
- [ ] DB 互換: テーブル/カラム/型/制約の差分なし。
- [ ] 振る舞い互換: 主要手動フローで機能差分なし。

## 影響範囲 (Impact/Scope)

- **触るファイル**:
  - `app.py`（最終的に互換レイヤーへ縮退）
  - `scheduler_agent/**`（新規）
  - 必要に応じて `mcp_server.py`（import 先調整が必要な場合のみ）
  - テスト補助ファイル（必要最小限）

- **壊しちゃいけない挙動**:
  - 既存ルートの URL/HTTP メソッド/レスポンスキー
  - チャット multi-step 実行と重複防止ロジック
  - execution trace の保存/復元
  - `asgi.py` からのアプリ起動
  - PostgreSQL 前提の初期化とセッション生成

## 実行コマンド目安 (Verification Commands)
```bash
# 軽量テスト
pytest tests/test_basic_api.py tests/test_major_endpoints.py tests/test_agent_result.py tests/test_frontend_react.py

# DB 利用可能時
pytest tests/test_app.py

# 起動確認
uvicorn app:app --reload --port 5000
```

## リスクと対策
- **リスク**: import 循環で起動失敗。
  - **対策**: `routers -> services -> models/core` の一方向依存を厳守。
- **リスク**: `app` 直参照テストが壊れる。
  - **対策**: `app.py` に互換再公開レイヤーを置き、移行中は名前を維持。
- **リスク**: route name 変更により `url_for` が破壊。
  - **対策**: route name を現行と一致させる自動確認テストを追加検討。
