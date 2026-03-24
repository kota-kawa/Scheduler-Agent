import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "../api/client";
import { DEFAULT_MODEL, INITIAL_GREETING } from "../utils/constants";
import { formatTimeFromIso, nowTime } from "../utils/time";
import type {
  ChatExecutionAction,
  ChatExecutionTrace,
  ChatHistoryResponse,
  ChatMessage,
  ChatResponse,
  ModelOption,
  ModelSettingsResponse,
  ModelsResponse,
} from "../types/api";
import type { ChatDisplayMessage } from "../types/ui";

const { createElement: h } = React;

const THINKING_STEPS = [
  "依頼内容を読み取っています",
  "予定データを確認しています",
  "必要な操作を実行しています",
  "回答を整えています",
];

const ACTION_LABELS: Record<string, string> = {
  resolve_schedule_expression: "日時を計算",
  create_custom_task: "予定を追加",
  delete_custom_task: "予定を削除",
  toggle_custom_task: "予定の完了状態を更新",
  update_custom_task_time: "予定時刻を変更",
  rename_custom_task: "予定名を変更",
  update_custom_task_memo: "予定メモを更新",
  toggle_step: "ルーチンの完了状態を更新",
  add_routine: "ルーチンを追加",
  delete_routine: "ルーチンを削除",
  update_routine_days: "ルーチン曜日を変更",
  add_step: "ステップを追加",
  delete_step: "ステップを削除",
  update_step_time: "ステップ時刻を変更",
  rename_step: "ステップ名を変更",
  update_step_memo: "ステップメモを更新",
  update_log: "日報を更新",
  append_day_log: "日報に追記",
  get_day_log: "日報を確認",
  get_daily_summary: "1日の予定を確認",
  list_tasks_in_period: "期間の予定を確認",
};

const PROMPT_EXAMPLES = [
  "明日の10時に『定例会議』を入れて。そのあと11時に『会議の振り返り』というタスクも追加して。",
  "今日の18時以降にある予定をすべて20時以降にずらして。",
  "『朝のルーチン』に8時の『ゴミ出し』ステップを追加して。あと、今日のゴミ出しはもう終わったから完了にしておいて。",
  "新しいルーチン『週末の掃除』を土日に作成して。ステップとして10時に『掃除機がけ』、11時に『お風呂掃除』を追加して。",
  "今日の日報に『今日は集中して作業できた』と追記して。それから今日のタスクを全部完了にして。",
];

const trimValue = (value: unknown, max = 24): string => {
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text) return "";
  if (text.length <= max) return text;
  return `${text.slice(0, max - 1)}…`;
};

const describeAction = (action: ChatExecutionAction): string => {
  const label = ACTION_LABELS[action.type] || action.type;
  const params = action.params || {};
  const name = trimValue(params.name);
  const date = trimValue(params.date);
  const time = trimValue(params.time);

  const hints = [name, date, time].filter((part) => !!part);
  if (hints.length > 0) return `${label}（${hints.join(" / ")}）`;
  return label;
};

const buildExecutionTraceSummary = (trace?: ChatExecutionTrace[]): string => {
  if (!Array.isArray(trace) || trace.length === 0) return "";

  const lines: string[] = [];
  let index = 1;
  for (const round of trace) {
    if (!round || !Array.isArray(round.actions)) continue;
    for (const action of round.actions) {
      lines.push(`${index}. ${describeAction(action)}`);
      index += 1;
    }
    if (Array.isArray(round.errors) && round.errors.length > 0) {
      lines.push(`- 注意: ${round.errors[0]}`);
    }
  }
  return lines.length > 0 ? lines.join("\n") : "";
};

interface ChatSidebarProps {
  onRefresh?: (ids?: Array<string | number>) => void;
  onModelChange?: (model: string) => void;
}

// 日本語: チャットサイドバー（モデル選択＋会話） / English: Chat sidebar (model selection + conversation)
export const ChatSidebar = ({ onRefresh, onModelChange }: ChatSidebarProps) => {
  // 日本語: UI 状態と選択モデル / English: UI state and selected model
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState(
    `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`
  );
  const [messages, setMessages] = useState<ChatDisplayMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isPaused, setIsPaused] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [thinkingStepIndex, setThinkingStepIndex] = useState(0);
  const [showExamples, setShowExamples] = useState(false);

  const historyRef = useRef<ChatMessage[]>([]);
  const baseUrlRef = useRef("");
  const skipNextModelUpdateRef = useRef(false);
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const selectOptions = useMemo(() => {
    if (modelOptions.length > 0) return modelOptions;
    return [{ ...DEFAULT_MODEL, label: "GPT-OSS 20B (Groq)" }];
  }, [modelOptions]);

  // 日本語: 表示用メッセージの追加 / English: Append a display message
  type AppendMessageOptions = {
    timestamp?: string;
    persistToHistory?: boolean;
    executionLog?: string;
  };

  const appendMessage = (
    role: ChatMessage["role"],
    content: string,
    options?: AppendMessageOptions
  ) => {
    const timestamp = options?.timestamp;
    const persistToHistory = options?.persistToHistory ?? true;
    const executionLog = typeof options?.executionLog === "string" ? options.executionLog.trim() : "";
    const timeDisplay = timestamp || nowTime();
    if (persistToHistory) {
      historyRef.current = [...historyRef.current, { role, content }];
    }
    setMessages((prev) => [
      ...prev,
      { role, content, timeDisplay, executionLog: executionLog || undefined },
    ]);
  };

  // 日本語: サーバーの履歴を復元 / English: Load chat history from server
  const loadChatHistory = async () => {
    try {
      const data = await fetchJson<ChatHistoryResponse>("/api/chat/history");
      if (data.history && data.history.length > 0) {
        const history = data.history.map((msg) => ({
          role: msg.role,
          content: msg.content,
          timeDisplay: formatTimeFromIso(msg.timestamp),
          executionLog: buildExecutionTraceSummary(msg.execution_trace),
        }));
        historyRef.current = data.history.map((msg) => ({
          role: msg.role,
          content: msg.content,
        }));
        setMessages(history);
      } else {
        historyRef.current = [];
        setMessages([{ role: "assistant", content: INITIAL_GREETING, timeDisplay: nowTime() }]);
        historyRef.current = [{ role: "assistant", content: INITIAL_GREETING }];
      }
    } catch (err) {
      console.error("Failed to load chat history", err);
      historyRef.current = [];
      setMessages([{ role: "assistant", content: INITIAL_GREETING, timeDisplay: nowTime() }]);
      historyRef.current = [{ role: "assistant", content: INITIAL_GREETING }];
    }
  };

  // 日本語: 選択モデルをサーバーへ反映 / English: Persist model selection
  const updateModelSelection = async (value: string) => {
    const fallbackValue = `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`;
    const [providerRaw, modelRaw] = (value || fallbackValue).split(":");
    const provider = providerRaw || DEFAULT_MODEL.provider;
    const model = modelRaw || DEFAULT_MODEL.model;
    const payload = { provider, model, base_url: baseUrlRef.current || "" };

    try {
      const res = await fetchJson<ModelSettingsResponse>("/model_settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      onModelChange?.(`${res.applied.provider}:${res.applied.model}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      console.error("Failed to update model:", err);
      alert(`モデルの更新に失敗しました: ${message}`);
    }
  };

  // 日本語: モデル候補一覧を取得 / English: Load model options
  const loadModelOptions = async () => {
    let nextValue = `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`;
    try {
      const data = await fetchJson<ModelsResponse>("/api/models", { cache: "no-store" });
      if (Array.isArray(data.models)) {
        setModelOptions(data.models.filter((m) => m && m.provider && m.model));
      } else {
        setModelOptions([]);
      }

      const current = data.current;
      if (current && typeof current === "object" && current.provider && current.model) {
        baseUrlRef.current = typeof current.base_url === "string" ? current.base_url : "";
        nextValue = `${current.provider}:${current.model}`;
      } else {
        baseUrlRef.current = "";
        nextValue = `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`;
      }
      setSelectedModel(nextValue);
    } catch (err) {
      console.error("Failed to load model options", err);
      setModelOptions([]);
      baseUrlRef.current = "";
      nextValue = `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`;
      setSelectedModel(nextValue);
    } finally {
      skipNextModelUpdateRef.current = true;
      await updateModelSelection(nextValue);
      onModelChange?.(nextValue);
    }
  };

  // 日本語: サーバーへチャットリクエスト送信 / English: Send chat request to server
  const requestAssistantResponse = async () => {
    const payload = {
      messages: historyRef.current.map(({ role, content }) => ({ role, content })),
    };

    return await fetchJson<ChatResponse>("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  };

  // 日本語: ユーザー送信処理 / English: Handle user submit
  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isPaused || isSending) return;
    const text = inputValue.trim();
    if (!text) return;

    appendMessage("user", text);
    setInputValue("");
    setIsSending(true);

    try {
      const data = await requestAssistantResponse();
      const executionSummary = buildExecutionTraceSummary(data.execution_trace);
      const reply = typeof data.reply === "string" ? data.reply : "";
      const cleanReply = reply && reply.trim();

      if (cleanReply) {
        appendMessage("assistant", cleanReply, { executionLog: executionSummary });
      } else if (data.should_refresh) {
        // 日本語: アクション実行時は返信が空でも「了解しました。」を表示 / English: Show confirmation if action was taken
        appendMessage("assistant", "了解しました。", { executionLog: executionSummary });
      } else if (executionSummary) {
        appendMessage("assistant", "処理内容を実行ログにまとめました。", {
          executionLog: executionSummary,
        });
      }

      if (data.should_refresh && onRefresh) {
        onRefresh(Array.isArray(data.modified_ids) ? data.modified_ids : []);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      appendMessage("assistant", `エラーが発生しました: ${message}`);
    } finally {
      setIsSending(false);
    }
  };

  // 日本語: 履歴リセット / English: Reset chat history
  const handleReset = async () => {
    if (!confirm("チャット履歴を削除しますか？")) return;

    try {
      await fetchJson<ChatHistoryResponse>("/api/chat/history", { method: "DELETE" });
    } catch (e) {
      console.error("Failed to clear history", e);
    }

    historyRef.current = [];
    setMessages([{ role: "assistant", content: INITIAL_GREETING, timeDisplay: nowTime() }]);
    historyRef.current = [{ role: "assistant", content: INITIAL_GREETING }];
    setIsPaused(false);
    setIsSending(false);
  };

  useEffect(() => {
    // 日本語: 初回ロード時にモデル/履歴を取得 / English: Load models and history on mount
    loadModelOptions();
    loadChatHistory();
  }, []);

  useEffect(() => {
    // 日本語: モデル変更時に保存 / English: Save when model changes
    if (skipNextModelUpdateRef.current) {
      skipNextModelUpdateRef.current = false;
      return;
    }
    updateModelSelection(selectedModel);
    onModelChange?.(selectedModel);
  }, [selectedModel]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [messages]);

  useEffect(() => {
    if (!isSending) {
      setThinkingStepIndex(0);
      return;
    }
    const intervalId = window.setInterval(() => {
      setThinkingStepIndex((prev) => {
        if (prev >= THINKING_STEPS.length - 1) return prev;
        return prev + 1;
      });
    }, 900);
    return () => window.clearInterval(intervalId);
  }, [isSending]);

  useEffect(() => {
    if (!isPaused && inputRef.current) {
      inputRef.current.focus();
    }
  }, [isPaused]);

  return h(
    "aside",
    { className: "sidebar", "aria-label": "Scheduler Agent" },
    h(
      "header",
      { className: "sidebar__header" },
      h(
        "div",
        { className: "sidebar__title" },
        h("span", { className: "sidebar__bubble" }, "💬"),
        h("h1", null, "Scheduler Agent"),
        h(
          "div",
          { className: "model-selection" },
          h("label", { htmlFor: "modelSelect", className: "sr-only" }, "モデルを選択"),
          h(
            "select",
            {
              id: "modelSelect",
              className: "model-selection__select",
              value: selectedModel,
              onChange: (e: React.ChangeEvent<HTMLSelectElement>) =>
                setSelectedModel(e.target.value),
            },
            selectOptions.map((m) => {
              const value = `${m.provider}:${m.model}`;
              const isSelectable = value === "groq:openai/gpt-oss-120b";
              return h("option", { key: value, value, disabled: !isSelectable }, m.label || value);
            })
          )
        )
      )
    ),
    h(
      "section",
      { className: "chat", id: "chat" },
      h(
        "div",
        {
          className: "chat__log",
          id: "chatLog",
          role: "log",
          "aria-live": "polite",
          "aria-relevant": "additions",
          ref: logRef,
        },
        messages.map((msg, idx) =>
          h(
            "div",
            { key: `${msg.role}-${idx}`, className: `message message--${msg.role}` },
            h("div", { className: "message__avatar" }, msg.role === "user" ? "👤" : "🤖"),
            h(
              "div",
              null,
              h(
                "div",
                { className: "message__bubble" },
                msg.executionLog
                  ? h(
                      "details",
                      { className: "message-exec-log" },
                      h("summary", { className: "message-exec-log__summary" }, "実行ログ（自動処理）"),
                      h("pre", { className: "message-exec-log__body" }, msg.executionLog)
                    )
                  : null,
                h("div", { className: "message__text" }, msg.content)
              ),
              h(
                "div",
                { className: "message__meta" },
                `${msg.role === "user" ? "あなた" : "LLM"} ・ ${msg.timeDisplay}`
              )
            )
          )
        ),
        isSending
          ? h(
              "div",
              { className: "message message--assistant message--thinking", key: "thinking-indicator" },
              h("div", { className: "message__avatar" }, "🤖"),
              h(
                "div",
                null,
                h(
                  "div",
                  { className: "message__bubble thinking-bubble" },
                  h(
                    "div",
                    { className: "thinking-bubble__title" },
                    "Thinking",
                    h(
                      "span",
                      { className: "thinking-bubble__dots", "aria-hidden": "true" },
                      h("i", null),
                      h("i", null),
                      h("i", null)
                    )
                  ),
                  h(
                    "div",
                    { className: "thinking-bubble__step" },
                    THINKING_STEPS[Math.min(thinkingStepIndex, THINKING_STEPS.length - 1)]
                  )
                ),
                h("div", { className: "message__meta" }, "LLM ・ 実行中")
              )
            )
          : null
      )
    ),
    h(
      "form",
      { className: "chat-controller", id: "chatForm", autoComplete: "off", onSubmit: handleSubmit },
      h("label", { htmlFor: "chatInput", className: "sr-only" }, "メッセージを入力"),
      showExamples &&
        h(
          "div",
          { className: "prompt-examples-popover" },
          h(
            "div",
            { className: "prompt-examples-popover__title" },
            h("span", null, "💡 複数ステップのタスク例"),
            h(
              "button",
              {
                type: "button",
                style: {
                  background: "none",
                  border: "none",
                  cursor: "pointer",
                  fontSize: "18px",
                  color: "var(--chat-muted)",
                },
                onClick: () => setShowExamples(false),
              },
              "×"
            )
          ),
          h(
            "ul",
            { className: "prompt-examples-list" },
            PROMPT_EXAMPLES.map((example, i) =>
              h(
                "li",
                {
                  key: i,
                  className: "prompt-example-item",
                  onClick: () => {
                    setInputValue(example);
                    setShowExamples(false);
                    inputRef.current?.focus();
                  },
                },
                example
              )
            )
          )
        ),
      h(
        "div",
        { className: "chat-controller__inner" },
        h(
          "div",
          { className: "chat-controller__input-container" },
          h(
            "button",
            {
              type: "button",
              className: "prompt-example-btn",
              onClick: () => setShowExamples(!showExamples),
              title: "プロンプトの例を表示",
              "aria-label": "プロンプト例",
            },
            "i"
          ),
          h("textarea", {
            id: "chatInput",
            className: "chat-controller__input",
            rows: 2,
            placeholder: "スケジューラーに指示を入力してください。",
            value: inputValue,
            onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) => setInputValue(e.target.value),
            disabled: isPaused,
            ref: inputRef,
          })
        ),
        h(
          "div",
          { className: "chat-controller__side" },
          h(
            "button",
            {
              type: "submit",
              className: "control-btn control-btn--send",
              id: "sendBtn",
              "aria-label": "送信",
              disabled: isPaused || isSending,
            },
            h("span", { "aria-hidden": "true" }, "➜")
          ),
          h(
            "div",
            { className: "control-btn__row" },
            h(
              "button",
              {
                type: "button",
                className: `control-btn${isPaused ? " is-active" : ""}`,
                id: "pauseBtn",
                "aria-label": "一時停止",
                "aria-pressed": isPaused,
                onClick: () => setIsPaused((prev) => !prev),
              },
              h("span", { "aria-hidden": "true" }, "⏸")
            ),
            h(
              "button",
              {
                type: "button",
                className: "control-btn",
                id: "chatResetBtn",
                "aria-label": "リセット",
                onClick: handleReset,
              },
              h("span", { "aria-hidden": "true" }, "⟲")
            )
          )
        )
      )
    )
  );
};
