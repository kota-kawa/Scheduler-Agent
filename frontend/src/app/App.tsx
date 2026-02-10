import React, { useEffect, useState } from "react";
import { fetchJson, stripPrefixFromPath } from "../api/client";
import { MainShell, StandaloneShell } from "../components/Shells";
import { CalendarPage } from "../pages/CalendarPage";
import { DayPage } from "../pages/DayPage";
import { EmbedCalendarPage } from "../pages/EmbedCalendarPage";
import { EvaluationPage } from "../pages/EvaluationPage";
import { RoutinesPage } from "../pages/RoutinesPage";
import type { FlashResponse } from "../types/api";

const { createElement: h } = React;

const App = () => {
  // 日本語: ルーティング用の現在パス / English: Current path for routing
  const path = stripPrefixFromPath(window.location.pathname || "/");
  // 日本語: 再描画トリガー群 / English: Refresh triggers
  const [refreshToken, setRefreshToken] = useState(0);
  const [refreshIds, setRefreshIds] = useState<Array<string | number>>([]);
  const [flashMessages, setFlashMessages] = useState<string[]>([]);
  const [currentModel, setCurrentModel] = useState("");

  // 日本語: 表示モードの判定 / English: Mode flags
  const isAgentResult = path === "/agent-result";
  const isAgentDay = path.startsWith("/agent-result/day/");
  const isEmbedCalendar = path.startsWith("/embed/calendar");
  const isStandalone = isAgentResult || isAgentDay || isEmbedCalendar;

  useEffect(() => {
    // 日本語: iframe 埋め込み時のスタイル調整 / English: Apply iframe-specific styling
    if (isStandalone && window.self !== window.top) {
      document.body.classList.add("iframe-hosted");
    }
    return () => {
      document.body.classList.remove("iframe-hosted");
    };
  }, [isStandalone]);

  useEffect(() => {
    // 日本語: フラッシュメッセージを取得 / English: Fetch flash messages on load
    fetchJson<FlashResponse>("/api/flash")
      .then((data) => setFlashMessages(Array.isArray(data.messages) ? data.messages : []))
      .catch(() => setFlashMessages([]));
  }, []);

  const handleRefresh = (ids?: Array<string | number>) => {
    // 日本語: ページ側へ再読み込みシグナル / English: Signal child pages to refresh
    setRefreshIds(ids || []);
    setRefreshToken(Date.now());
  };

  // 日本語: パスに応じてページを切り替え / English: Route to the correct page component
  let content: React.ReactNode = null;

  if (path === "/" || path.startsWith("/index")) {
    content = h(CalendarPage, {
      dayLinkBase: "/day/",
      showModal: true,
      showSampleButton: true,
      basePath: "/",
      refreshToken,
    });
  } else if (path.startsWith("/day/")) {
    const dateStr = path.split("/")[2] || "";
    content = h(DayPage, {
      dateStr,
      isStandalone: false,
      refreshToken,
      refreshIds,
      basePath: "/",
    });
  } else if (path === "/routines") {
    content = h(RoutinesPage, { refreshToken });
  } else if (path === "/evaluation") {
    content = h(EvaluationPage, { currentModel });
  } else if (isAgentResult) {
    content = h(CalendarPage, {
      dayLinkBase: "/agent-result/day/",
      showModal: true,
      showSampleButton: false,
      basePath: "/agent-result",
      refreshToken,
    });
  } else if (isAgentDay) {
    const dateStr = path.split("/")[3] || "";
    content = h(DayPage, {
      dateStr,
      isStandalone: true,
      refreshToken,
      refreshIds,
      basePath: "/agent-result",
    });
  } else if (isEmbedCalendar) {
    content = h(EmbedCalendarPage);
  } else {
    content = h("div", { className: "alert alert-warning" }, "ページが見つかりません。");
  }

  if (isEmbedCalendar) {
    // 日本語: 埋め込み表示はシェル無し / English: Embedded view without shells
    return content;
  }

  if (isStandalone) {
    // 日本語: スタンドアロン表示（ヘッダ無し） / English: Standalone shell
    return h(StandaloneShell, null, content);
  }

  // 日本語: 通常表示（ヘッダ/ナビ付き） / English: Main shell with navigation
  return h(MainShell, {
    onRefresh: handleRefresh,
    flashMessages,
    onModelChange: setCurrentModel,
    children: content,
  });
};

export default App;
