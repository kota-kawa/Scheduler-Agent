import React, { Fragment, useMemo, useRef, useState } from "react";
import { fetchJson, withPrefix } from "../api/client";
import type { ChatMessage, EvaluationChatResponse, EvaluationSeedResponse } from "../types/api";
import type { EvaluationRow } from "../types/ui";

const { createElement: h } = React;

interface EvaluationPageProps {
  currentModel: string;
}

export const EvaluationPage = ({ currentModel }: EvaluationPageProps) => {
  const scenarios = useMemo(
    () => [
      "「洗剤を買う」というタスクを追加して。",
      "明日から明後日までの予定を教えて。",
      "「洗剤を買う」を「柔軟剤を買う」に名前を変えて。",
      "「柔軟剤を買う」タスク、完了しました。",
      "明日の15:30分から「歯医者」の予定を入れて。",
      "やっぱり「柔軟剤を買う」は削除して。そして、「歯医者」のタスクに「保険証を忘れない」というメモを追加しておいて。",
      "「筋トレ」という新しいルーチンを作って。月曜と木曜にやるよ。",
      "さっき作った「筋トレ」ルーチンに、「スクワット」というステップ（10分）を追加して。",
      "「筋トレ」ルーチン、やっぱり土曜日もやることにする。",
      "先週の金曜日の日報を見せて。",
    ],
    []
  );

  const [rows, setRows] = useState<EvaluationRow[]>(
    scenarios.map((prompt) => ({
      prompt,
      loading: false,
      reply: null,
      toolsText: null,
      judgment: null,
      toolCalls: [],
    }))
  );
  const conversationRef = useRef<ChatMessage[]>([]);

  const refreshCalendarFrame = () => {
    const calFrame = document.getElementById("calendarFrame") as HTMLIFrameElement | null;
    if (calFrame && calFrame.contentWindow) {
      calFrame.contentWindow.location.reload();
    }
  };

  const runScenario = async (index: number) => {
    setRows((prev) => prev.map((row, idx) => (idx === index ? { ...row, loading: true } : row)));

    const prompt = rows[index].prompt;
    const currentMessages = [...conversationRef.current, { role: "user", content: prompt }];
    const payloadMessages = currentMessages.slice(-10);

    try {
      const data = await fetchJson<EvaluationChatResponse>("/api/evaluation/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: payloadMessages }),
      });

      conversationRef.current = [
        ...conversationRef.current,
        { role: "user", content: prompt },
        { role: "assistant", content: data.reply },
      ];

      let toolsText = "";
      if (data.actions && data.actions.length > 0) {
        toolsText = `Tools Used:\n${JSON.stringify(data.actions, null, 2)}`;
      } else {
        toolsText = "(No tool calls)";
      }
      if (data.results && data.results.length > 0) {
        toolsText += `\n\nResults:\n${data.results.join("\n")}`;
      }
      if (data.errors && data.errors.length > 0) {
        toolsText += `\n\nErrors:\n${data.errors.join("\n")}`;
      }

      setRows((prev) =>
        prev.map((row, idx) =>
          idx === index
            ? {
                ...row,
                loading: false,
                reply: data.reply,
                toolsText,
                judgment: null,
                toolCalls: data.actions || [],
              }
            : row
        )
      );

      refreshCalendarFrame();
    } catch (err) {
      console.error(err);
      const message = err instanceof Error ? err.message : "Unknown error";
      setRows((prev) =>
        prev.map((row, idx) => (idx === index ? { ...row, loading: false, reply: `エラー: ${message}` } : row))
      );
    }
  };

  const logResult = async (index: number, isSuccess: boolean) => {
    const row = rows[index];
    if (!row.reply) return;
    try {
      await fetchJson("/api/evaluation/log", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model_name: currentModel || "unknown",
          task_prompt: row.prompt,
          agent_reply: row.reply,
          tool_calls: row.toolCalls || [],
          is_success: isSuccess,
        }),
      });
      setRows((prev) =>
        prev.map((r, idx) => (idx === index ? { ...r, judgment: isSuccess ? "OK" : "NG" } : r))
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      alert(`ログ保存失敗: ${message}`);
    }
  };

  const handleSeed = async () => {
    if (!confirm("サンプルデータを追加しますか？（先週金曜の日報などが作成されます）")) return;
    try {
      const data = await fetchJson<EvaluationSeedResponse>("/api/evaluation/seed", { method: "POST" });
      alert(data.message || data.error);
      refreshCalendarFrame();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      alert(`エラー: ${message}`);
    }
  };

  const handleSeedPeriod = async () => {
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const dayAfter = new Date(today);
    dayAfter.setDate(dayAfter.getDate() + 2);
    const formatDate = (d: Date) => d.toISOString().split("T")[0];
    const startDate = formatDate(tomorrow);
    const endDate = formatDate(dayAfter);

    if (!confirm(`明日(${startDate})から明後日(${endDate})にサンプル予定を追加しますか？`)) return;
    try {
      const data = await fetchJson<EvaluationSeedResponse>("/api/evaluation/seed_period", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_date: startDate, end_date: endDate }),
      });
      alert(data.message || data.error);
      refreshCalendarFrame();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      alert(`エラー: ${message}`);
    }
  };

  const handleReset = async () => {
    if (!confirm("本当に全データを削除しますか？")) return;
    try {
      const data = await fetchJson<EvaluationSeedResponse>("/api/evaluation/reset", { method: "POST" });
      conversationRef.current = [];
      alert(data.message || data.error);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      alert(`エラー: ${message}`);
    }
  };

  return h(
    Fragment,
    null,
    h(
      "div",
      { className: "d-flex justify-content-between align-items-center mb-4" },
      h("h2", null, h("i", { className: "bi bi-clipboard-check me-2" }), "評価・テスト実行"),
      h(
        "div",
        null,
        h(
          "button",
          { id: "seedBtn", className: "btn btn-outline-success me-2", onClick: handleSeed },
          h("i", { className: "bi bi-database-add me-1" }),
          "サンプルデータ追加"
        ),
        h(
          "button",
          { id: "seedPeriodBtn", className: "btn btn-outline-info me-2", onClick: handleSeedPeriod },
          h("i", { className: "bi bi-calendar-range me-1" }),
          "明日〜明後日データ追加"
        ),
        h(
          "button",
          { id: "resetBtn", className: "btn btn-outline-danger", onClick: handleReset },
          h("i", { className: "bi bi-trash me-1" }),
          "全データ削除"
        )
      )
    ),
    h(
      "div",
      { className: "alert alert-light border shadow-sm mb-4" },
      h(
        "h5",
        { className: "alert-heading" },
        h("i", { className: "bi bi-info-circle me-2" }),
        "使い方"
      ),
      h(
        "p",
        { className: "mb-0 small text-muted" },
        "左サイドバーでモデルを選択し、以下のシナリオを順に実行して動作を確認してください。",
        h("br"),
        "「サンプルデータ追加」を押すと、テストに必要な過去ログ（先週金曜日）が生成されます。",
        h("br"),
        "「明日〜明後日データ追加」を押すと、明日と明後日にサンプル予定が追加されます（「明日から明後日までの予定を教えて」のテスト用）。",
        h("br"),
        "「全データ削除」を押すと、スケジューラーの全データが初期化されます。"
      )
    ),
    h(
      "div",
      { className: "card shadow-sm mb-4" },
      h(
        "div",
        { className: "card-header bg-white d-flex justify-content-between align-items-center py-3" },
        h("h5", { className: "mb-0" }, "テストシナリオ一覧"),
        h(
          "button",
          {
            id: "runAllBtn",
            className: "btn btn-primary btn-sm",
            disabled: true,
            onClick: () => alert("順次実行はまだ実装されていません。各行の実行ボタンを押してください。"),
          },
          h("i", { className: "bi bi-play-circle me-1" }),
          "一括実行 (未実装)"
        )
      ),
      h(
        "div",
        { className: "table-responsive" },
        h(
          "table",
          { className: "table table-hover align-middle mb-0", id: "evalTable" },
          h(
            "thead",
            { className: "table-light" },
            h(
              "tr",
              null,
              h("th", { style: { width: "5%" } }, "#"),
              h("th", { style: { width: "35%" } }, "指示 (Prompt)"),
              h("th", { style: { width: "40%" } }, "実行結果 (Result)"),
              h("th", { style: { width: "20%" }, className: "text-center" }, "操作 / 判定")
            )
          ),
          h(
            "tbody",
            { id: "evalTableBody" },
            rows.map((row, idx) =>
              h(
                "tr",
                { key: row.prompt, className: "eval-row" },
                h("td", { className: "row-index fw-bold text-muted" }, idx + 1),
                h("td", { className: "row-prompt text-wrap", style: { maxWidth: "300px" } }, row.prompt),
                h(
                  "td",
                  { className: "row-result" },
                  row.reply
                    ? h(
                        "div",
                        { className: "result-content" },
                        h("div", { className: "agent-reply mb-2 small bg-light p-2 rounded" }, row.reply),
                        h("div", { className: "tool-calls small font-monospace text-primary" }, row.toolsText)
                      )
                    : h("div", { className: "result-placeholder text-muted small" }, row.loading ? "実行中..." : "未実行")
                ),
                h(
                  "td",
                  { className: "text-center" },
                  h(
                    "button",
                    {
                      className: "btn btn-sm btn-outline-primary run-btn",
                      onClick: () => runScenario(idx),
                      disabled: row.loading,
                    },
                    row.loading
                      ? h("span", { className: "spinner-border spinner-border-sm" })
                      : h("i", { className: row.reply ? "bi bi-arrow-repeat" : "bi bi-play-fill" }),
                    " ",
                    row.reply ? "再実行" : "実行"
                  ),
                  row.reply
                    ? h(
                        "div",
                        { className: "judgment-btns mt-2" },
                        h(
                          "button",
                          {
                            className: "btn btn-sm btn-success success-btn me-1",
                            title: "成功",
                            onClick: () => logResult(idx, true),
                          },
                          h("i", { className: "bi bi-check-lg" })
                        ),
                        h(
                          "button",
                          {
                            className: "btn btn-sm btn-danger fail-btn",
                            title: "失敗",
                            onClick: () => logResult(idx, false),
                          },
                          h("i", { className: "bi bi-x-lg" })
                        )
                      )
                    : null,
                  row.judgment
                    ? h(
                        "div",
                        {
                          className: `judgment-result mt-2 fw-bold small text-${
                            row.judgment === "OK" ? "success" : "danger"
                          }`,
                        },
                        `判定: ${row.judgment}`
                      )
                    : null
                )
              )
            )
          )
        )
      )
    ),
    h(
      "div",
      { className: "card shadow-sm mb-4" },
      h(
        "div",
        { className: "card-header bg-white py-3" },
        h("h5", { className: "mb-0" }, "カレンダー確認")
      ),
      h(
        "div",
        { className: "card-body p-0" },
        h("iframe", {
          id: "calendarFrame",
          src: withPrefix("/embed/calendar"),
          style: { width: "100%", height: "600px", border: "none" },
        })
      )
    )
  );
};
