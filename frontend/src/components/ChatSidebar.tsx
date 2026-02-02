import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchJson } from "../api/client";
import { DEFAULT_MODEL, INITIAL_GREETING } from "../utils/constants";
import { formatTimeFromIso, nowTime } from "../utils/time";
import type {
  ChatHistoryResponse,
  ChatMessage,
  ChatResponse,
  ModelOption,
  ModelSettingsResponse,
  ModelsResponse,
} from "../types/api";
import type { ChatDisplayMessage } from "../types/ui";

const { createElement: h } = React;

interface ChatSidebarProps {
  onRefresh?: (ids?: Array<string | number>) => void;
  onModelChange?: (model: string) => void;
}

export const ChatSidebar = ({ onRefresh, onModelChange }: ChatSidebarProps) => {
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState(
    `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`
  );
  const [messages, setMessages] = useState<ChatDisplayMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isPaused, setIsPaused] = useState(false);
  const [isSending, setIsSending] = useState(false);

  const historyRef = useRef<ChatMessage[]>([]);
  const baseUrlRef = useRef("");
  const skipNextModelUpdateRef = useRef(false);
  const logRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const selectOptions = useMemo(() => {
    if (modelOptions.length > 0) return modelOptions;
    return [{ ...DEFAULT_MODEL, label: "GPT-OSS 20B (Groq)" }];
  }, [modelOptions]);

  const appendMessage = (role: ChatMessage["role"], content: string, timestamp?: string) => {
    const timeDisplay = timestamp || nowTime();
    historyRef.current = [...historyRef.current, { role, content }];
    setMessages((prev) => [...prev, { role, content, timeDisplay }]);
  };

  const loadChatHistory = async () => {
    try {
      const data = await fetchJson<ChatHistoryResponse>("/api/chat/history");
      if (data.history && data.history.length > 0) {
        const history = data.history.map((msg) => ({
          role: msg.role,
          content: msg.content,
          timeDisplay: formatTimeFromIso(msg.timestamp),
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
      const reply = typeof data.reply === "string" ? data.reply : "";
      const cleanReply = reply && reply.trim();
      appendMessage("assistant", cleanReply || "了解しました。");

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
    loadModelOptions();
    loadChatHistory();
  }, []);

  useEffect(() => {
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
              return h("option", { key: value, value }, m.label || value);
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
              h("div", { className: "message__bubble" }, msg.content),
              h(
                "div",
                { className: "message__meta" },
                `${msg.role === "user" ? "あなた" : "LLM"} ・ ${msg.timeDisplay}`
              )
            )
          )
        )
      )
    ),
    h(
      "form",
      { className: "chat-controller", id: "chatForm", autoComplete: "off", onSubmit: handleSubmit },
      h("label", { htmlFor: "chatInput", className: "sr-only" }, "メッセージを入力"),
      h(
        "div",
        { className: "chat-controller__inner" },
        h("textarea", {
          id: "chatInput",
          className: "chat-controller__input",
          rows: 2,
          placeholder: "スケジューラーに指示を入力してください。",
          value: inputValue,
          onChange: (e: React.ChangeEvent<HTMLTextAreaElement>) =>
            setInputValue(e.target.value),
          disabled: isPaused,
          ref: inputRef,
        }),
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
