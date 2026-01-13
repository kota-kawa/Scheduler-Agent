# Scheduler Agent 📅

[English](README_en.md)

<img src="static/Scheduler-Agent-Logo.png" alt="Scheduler Agent Logo" width="800">

## 👋 はじめに

**Scheduler-Agent** へようこそ！
これは、あなたの毎日をちょっと便利にする、AI搭載のスケジュール管理アシスタントです。

「明日の予定は？」「来週の火曜日に買い物リストを追加して」
そんな風にチャットで話しかけるだけで、AIがあなたの代わりにスケジュールを整理してくれます。
日々のルーチンも、急なタスクも、ひとつのタイムラインで見やすく管理しましょう！✨

## ✨ できること

*   **📅 タイムライン表示**
    毎日のルーチンと、その日だけのタスクを時系列でスッキリ表示。「今なにをすべきか」がひと目で分かります。

*   **💬 チャットでかんたん操作**
    難しい操作は不要です。LINEやチャットアプリのように、AIに話しかけるだけで予定の追加や確認ができます。

*   **🤖 賢いAIがお手伝い**
    OpenAI (GPT) や Google (Gemini)、Anthropic (Claude) など、最新のAIモデルがあなたの秘書になります。気分に合わせてAIを切り替えることも可能です。

---

## 🚀 すぐに始める (推奨)

パソコンに **Docker** が入っていれば、すぐに使い始めることができます。

### 1. 🔑 準備：AIの鍵 (APIキー) をセット
まずは「AIへのパスポート」である **APIキー** を設定しましょう。
プロジェクトのフォルダに `secrets.env` という名前のファイルを作り、持っているキーを書き込みます。

```env
# secrets.env ファイルの中身 (例)
# 少なくとも1つあればOKです！

OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
ANTHROPIC_API_KEY=sk-ant-...
```

### 2. ▶️ 起動：コマンドをひとつ実行
ターミナル（黒い画面）で、以下の魔法のコマンドを入力してください。

```bash
docker compose up --build
```

### 3. 🌐 アクセス：ブラウザを開く
しばらくして文字が流れ止まったら、準備完了です！
以下のリンクをクリックして、アシスタントに会いに行きましょう。

👉 [http://localhost:5010](http://localhost:5010)

---

## 🛠️ 開発者向け (ローカル実行)

Pythonを使って直接動かしたい方はこちら。
高速なツール **uv** を使っているので、セットアップも爆速です⚡️

### 1. 📦 uv のインストール
まだの方は、こちらからインストール！

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. 🏗️ 環境をつくる
コマンド一発で、必要なライブラリを全部揃えます。

```bash
uv sync
```

### 3. 🗄️ データベースの用意
PostgreSQLというデータベースが必要です。
ローカルで動かして、`secrets.env` に接続情報を書いてください。

```env
# 例
DATABASE_URL=postgresql+psycopg2://user:password@localhost:5432/scheduler
```

### 4. ▶️ スタート
さあ、起動しましょう！

```bash
uv run uvicorn app:app --reload --port 5000
```
起動したら [http://localhost:5000](http://localhost:5000) へアクセスしてください。

---

## 📜 ライセンス

このプロジェクトは [MIT License](LICENSE.md) で公開されています。
自由に改変して、あなただけの最強アシスタントを作ってみてください！ 🛠️
