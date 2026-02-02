# Project Specifications & Guidelines

## 全体ルール (General Rules)
<!-- プロジェクト全体で遵守すべき原則 -->
- [ ] UI は React + TypeScript の SPA に一本化し、サーバーサイドテンプレートでの画面生成は行わない
- [ ] FastAPI は **API と SPA シェルの配信**に専念し、画面ルーティングはフロント側で担う
- [ ] 既存 API 契約（パス、メソッド、ペイロード、レスポンス）を破壊しない
- [ ] `static/spa/` にビルド成果物を出力し、`templates/spa.html` は最小のシェルとして維持する
- [ ] `meta[name="proxy-prefix"]` の値を尊重し、リバースプロキシ下でも動作する
- [ ] 画面/機能のパリティを最優先（新機能やデザイン刷新は二次）
- [ ] アクセシビリティ（ラベル、キーボード操作、コントラスト）を最低限担保する

## 対象機能一覧 (Feature Parity Checklist)
<!-- 既存 UI で提供している機能の移行対象 -->
- [ ] カレンダー（月表示・前後移動・今日ハイライト・達成率表示・日報アイコン）
- [ ] 日別画面（ルーチン進捗、メモ、保存、日報の保存）
- [ ] カスタムタスク（追加/削除/完了/メモ）
- [ ] ルーチン管理（一覧、曜日割当、ステップ追加/削除/並び）
- [ ] チャット UI（履歴取得/削除、送信、応答、ハイライト反映）
- [ ] モデル選択 UI（`/api/models` 取得、`/model_settings` 更新）
- [ ] 評価 UI（`/api/evaluation/*` の seed/reset/log/history）
- [ ] フラッシュ通知（`/api/flash` の表示）

## 画面ルーティング (SPA Routes)
<!-- 既存の HTML ルートを SPA で再現 -->
- [ ] `/` (index)
- [ ] `/agent-result`
- [ ] `/agent-result/day/:dateStr`
- [ ] `/embed-calendar`
- [ ] `/day/:dateStr`
- [ ] `/routines`
- [ ] `/evaluation`

## API 契約 (API Contract - existing)
<!-- 既存 API を前提に SPA を構築する -->
- [ ] `GET /api/calendar`
- [ ] `GET /api/day/{date_str}`
- [ ] `GET /api/routines`
- [ ] `GET /api/routines/day/{weekday}`
- [ ] `GET /api/models`
- [ ] `GET /api/flash`
- [ ] `GET|DELETE /api/chat/history`
- [ ] `POST /api/chat`
- [ ] `POST /api/evaluation/chat`
- [ ] `POST /api/evaluation/reset`
- [ ] `POST /api/evaluation/seed`
- [ ] `POST /api/evaluation/seed_period`
- [ ] `POST /api/evaluation/log`
- [ ] `GET /api/evaluation/history`
- [ ] `POST /api/add_sample_data`
- [ ] 既存フォーム系エンドポイント（`/routines/add` など）は SPA からも利用可能にする（FormData 送信 or API 化）
- [ ] モデル設定更新は `POST /model_settings` で JSON 送信する

## コーディング規約 (Coding Conventions)
<!-- 言語ごとのスタイルガイド、フォーマッター設定など -->
- **Python**:
  - バックエンドは変更最小限、既存の PEP 8 / 型ヒント方針に従う
- **JavaScript/React**:
  - React は関数コンポーネント + Hooks を原則とする
  - TypeScript は `strict` 前提、`any` は原則禁止（必要なら理由コメント）
  - `fetch` は共通 API クライアント経由でのみ使用
  - `async/await` を使用し、エラーは UI に明示する
  - CSS は既存 `styles/app.css` を基準に整理し、クラス名は `kebab-case` を維持

## 命名規則 (Naming Conventions)
<!-- 変数、関数、クラス、ファイル名の命名ルール -->
- **Variables/Functions**: `camelCase`
- **Classes/Components**: `PascalCase`
- **Hooks**: `useXxx`
- **Types/Interfaces**: `Xxx`, `XxxResponse`, `XxxPayload`
- **Files**: `kebab-case` or `PascalCase`（コンポーネントは `PascalCase.tsx`）
- **Constants**: `UPPER_SNAKE_CASE`

## ディレクトリ構成方針 (Directory Structure Policy)
<!-- ファイルの配置ルール、モジュール分割の方針 -->
- `frontend/src/` を SPA のソースルートとする
- 例:
  - `frontend/src/app/`（ルーティング/ルート設定/プロバイダ）
  - `frontend/src/pages/`（画面単位）
  - `frontend/src/components/`（再利用 UI）
  - `frontend/src/hooks/`（データ取得や状態管理の Hooks）
  - `frontend/src/api/`（API クライアントと型）
  - `frontend/src/types/`（ドメイン型）
  - `frontend/src/utils/`（日付/フォーマットなど）
  - `frontend/src/styles/`（共通スタイル）

## エラーハンドリング方針 (Error Handling Policy)
<!-- 例外処理、ログ出力、ユーザーへのフィードバック方法 -->
- API 失敗時は `ApiError` に統一（`status`, `message`, `detail`）し UI で表示
- 重要操作は UI 上で再試行手段を提供する
- 予期しない例外はグローバルエラーバウンダリで捕捉し、ユーザーへ簡潔に案内する
- サーバーが HTML を返した場合も検知し、ユーザーに「通信失敗」として明示する

## テスト方針 (Testing Policy)
<!-- テストの種類、カバレッジ目標、使用ツール -->
- **Unit Tests**: 
  - ユーティリティ/型変換/ API クライアントは Vitest を推奨（導入時）
- **E2E Tests**:
  - 既存は手動検証を必須とし、主要フローの手順を task.md に記載
  - 導入する場合は Playwright を推奨し、主要画面のスモークを整備
