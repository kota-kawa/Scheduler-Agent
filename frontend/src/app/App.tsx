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
  const path = stripPrefixFromPath(window.location.pathname || "/");
  const [refreshToken, setRefreshToken] = useState(0);
  const [refreshIds, setRefreshIds] = useState<Array<string | number>>([]);
  const [flashMessages, setFlashMessages] = useState<string[]>([]);
  const [currentModel, setCurrentModel] = useState("");

  const isAgentResult = path === "/agent-result";
  const isAgentDay = path.startsWith("/agent-result/day/");
  const isEmbedCalendar = path.startsWith("/embed/calendar");
  const isStandalone = isAgentResult || isAgentDay || isEmbedCalendar;

  useEffect(() => {
    if (isStandalone && window.self !== window.top) {
      document.body.classList.add("iframe-hosted");
    }
    return () => {
      document.body.classList.remove("iframe-hosted");
    };
  }, [isStandalone]);

  useEffect(() => {
    fetchJson<FlashResponse>("/api/flash")
      .then((data) => setFlashMessages(Array.isArray(data.messages) ? data.messages : []))
      .catch(() => setFlashMessages([]));
  }, []);

  const handleRefresh = (ids?: Array<string | number>) => {
    setRefreshIds(ids || []);
    setRefreshToken(Date.now());
  };

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
    return content;
  }

  if (isStandalone) {
    return h(StandaloneShell, null, content);
  }

  return h(MainShell, {
    onRefresh: handleRefresh,
    flashMessages,
    onModelChange: setCurrentModel,
    children: content,
  });
};

export default App;
