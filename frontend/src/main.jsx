/* Scheduler Agent UI (full React render) */

import React, { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import "./style.css";

const { createElement: h } = React;

const nowTime = () => {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
};

const formatTimeFromIso = (timestamp) => {
  try {
    const d = new Date(timestamp);
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  } catch (e) {
    return nowTime();
  }
};

const proxyPrefixMeta = document.querySelector("meta[name='proxy-prefix']");
const proxyPrefixRaw = (proxyPrefixMeta?.content || "").trim();
const proxyPrefix = proxyPrefixRaw === "/" ? "" : proxyPrefixRaw.replace(/\/+$/, "");

function withPrefix(path = "/") {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (!proxyPrefix) return normalized;
  const cleaned = proxyPrefix.startsWith("/") ? proxyPrefix : `/${proxyPrefix}`;
  return `${cleaned}${normalized}`.replace(/\/{2,}/g, "/");
}

function stripPrefixFromPath(path) {
  if (!proxyPrefix) return path || "/";
  const cleaned = proxyPrefix.startsWith("/") ? proxyPrefix : `/${proxyPrefix}`;
  if (path && path.startsWith(cleaned)) {
    const stripped = path.slice(cleaned.length);
    return stripped.startsWith("/") ? stripped : `/${stripped || ""}`;
  }
  return path || "/";
}

const DEFAULT_MODEL = { provider: "groq", model: "openai/gpt-oss-20b", base_url: "" };
const INITIAL_GREETING =
  "こんにちは！スケジューラーの確認やタスク登録をお手伝いします。やりたいことを日本語で教えてください。";
const DAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"];

async function fetchJson(path, options) {
  const res = await fetch(withPrefix(path), options);
  if (!res.ok) {
    const errText = await res.text();
    throw new Error(errText || `HTTP ${res.status}`);
  }
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error("Response is not JSON");
  }
  return await res.json();
}

function getMonthNav(year, month) {
  let prevMonth = month - 1;
  let prevYear = year;
  if (prevMonth < 1) {
    prevMonth = 12;
    prevYear = year - 1;
  }
  let nextMonth = month + 1;
  let nextYear = year;
  if (nextMonth > 12) {
    nextMonth = 1;
    nextYear = year + 1;
  }
  return { prevMonth, prevYear, nextMonth, nextYear };
}

function highlightIds(ids) {
  if (!Array.isArray(ids)) return;
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.classList.remove("flash-highlight");
      void el.offsetWidth;
      el.classList.add("flash-highlight");
      setTimeout(() => el.classList.remove("flash-highlight"), 2000);
    }
  });
}

function useCalendarData(yearParam, monthParam, refreshToken) {
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    let isActive = true;
    const load = async () => {
      setState({ loading: true, data: state.data, error: null });
      try {
        const params = new URLSearchParams();
        if (yearParam) params.set("year", yearParam);
        if (monthParam) params.set("month", monthParam);
        const query = params.toString();
        const url = query ? `/api/calendar?${query}` : "/api/calendar";
        const data = await fetchJson(url);
        if (!isActive) return;
        setState({ loading: false, data, error: null });
      } catch (err) {
        if (!isActive) return;
        setState({ loading: false, data: null, error: err.message });
      }
    };
    load();
    return () => {
      isActive = false;
    };
  }, [yearParam, monthParam, refreshToken]);

  return state;
}

function useDayData(dateStr, refreshToken) {
  const [state, setState] = useState({ loading: true, data: null, error: null });

  useEffect(() => {
    let isActive = true;
    const load = async () => {
      if (!dateStr) {
        setState({ loading: false, data: null, error: "Invalid date" });
        return;
      }
      setState({ loading: true, data: state.data, error: null });
      try {
        const data = await fetchJson(`/api/day/${dateStr}`);
        if (!isActive) return;
        setState({ loading: false, data, error: null });
      } catch (err) {
        if (!isActive) return;
        setState({ loading: false, data: null, error: err.message });
      }
    };
    load();
    return () => {
      isActive = false;
    };
  }, [dateStr, refreshToken]);

  return state;
}

function CalendarGrid({ calendarData, today, dayLinkBase }) {
  if (!calendarData) return null;
  return h(
    "div",
    { className: "calendar-grid", id: "calendar-grid" },
    calendarData.map((week, weekIdx) =>
      week.map((day) => {
        const isToday = day.date === today;
        const className = [
          "calendar-day",
          !day.is_current_month ? "not-current-month" : "",
          isToday ? "today-highlight" : "",
        ]
          .filter(Boolean)
          .join(" ");
        const ratio = day.total_steps > 0 ? day.completed_steps / day.total_steps : 0;
        const inlineStyle =
          day.total_routines === 0 && day.has_day_log
            ? { backgroundColor: "#f0f9ff", border: "1px solid #bae6fd" }
            : null;
        const dayUrl = withPrefix(`${dayLinkBase}${day.date}`);

        return h(
          "div",
          {
            key: `${weekIdx}-${day.date}`,
            className,
            style: inlineStyle || undefined,
            onClick: () => {
              window.location.href = dayUrl;
            },
          },
          h(
            "div",
            { className: "d-flex justify-content-between align-items-start" },
            h("span", { className: `day-number ${!day.is_current_month ? "text-muted" : ""}` }, day.day_num),
            h(
              "div",
              { className: "d-flex gap-1" },
              day.has_day_log
                ? h("i", { className: "bi bi-journal-text text-primary", title: "日報あり" })
                : null,
              day.total_steps > 0
                ? ratio === 1
                  ? h("i", { className: "bi bi-check-circle-fill text-success" })
                  : ratio > 0
                    ? h(
                        "div",
                        {
                          className: "spinner-border spinner-border-sm text-primary",
                          role: "status",
                          style: { width: "1rem", height: "1rem", borderWidth: "2px" },
                        },
                        h("span", { className: "visually-hidden" }, "In Progress")
                      )
                    : h("i", { className: "bi bi-circle text-muted", style: { fontSize: "0.8rem" } })
                : null
            )
          ),
          day.total_routines > 0
            ? h(
                "div",
                { className: "mt-3" },
                h(
                  "div",
                  { className: "progress", style: { height: "6px", borderRadius: "3px" } },
                  h("div", {
                    className: `progress-bar ${ratio === 1 ? "bg-success" : "bg-primary"}`,
                    role: "progressbar",
                    style: { width: `${ratio * 100}%` },
                  })
                ),
                h(
                  "div",
                  { className: "d-flex justify-content-between mt-1" },
                  h(
                    "small",
                    { className: "text-muted", style: { fontSize: "0.7rem" } },
                    `${day.completed_steps}/${day.total_steps} ステップ`
                  )
                )
              )
            : day.has_day_log
              ? h(
                  "div",
                  { className: "mt-3" },
                  h(
                    "small",
                    { className: "text-primary", style: { fontSize: "0.75rem" } },
                    h("i", { className: "bi bi-pencil-square me-1" }),
                    "Log recorded"
                  )
                )
              : null
        );
      })
    )
  );
}

function DayRoutinesModal({ modalRef, modalState }) {
  return h(
    "div",
    { className: "modal fade", id: "dayRoutineModal", tabIndex: "-1", "aria-hidden": "true", ref: modalRef },
    h(
      "div",
      { className: "modal-dialog modal-lg modal-dialog-centered" },
      h(
        "div",
        { className: "modal-content" },
        h(
          "div",
          { className: "modal-header" },
          h("h5", { className: "modal-title", id: "dayRoutineModalLabel" }, modalState.title),
          h("button", { type: "button", className: "btn-close", "data-bs-dismiss": "modal", "aria-label": "Close" })
        ),
        h(
          "div",
          { className: "modal-body", id: "dayRoutineModalBody" },
          modalState.loading
            ? h(
                "div",
                { className: "text-center py-5" },
                h(
                  "div",
                  { className: "spinner-border text-primary", role: "status" },
                  h("span", { className: "visually-hidden" }, "Loading...")
                )
              )
            : modalState.error
              ? h(
                  "div",
                  { className: "alert alert-danger" },
                  "データの取得に失敗しました。"
                )
              : modalState.routines.length === 0
                ? h(
                    "div",
                    { className: "text-center py-5" },
                    h("i", { className: "bi bi-calendar-x display-4 text-muted mb-3" }),
                    h("p", { className: "text-muted" }, "この曜日に登録されているルーチンはありません。")
                  )
                : h(
                    "div",
                    { className: "list-group list-group-flush" },
                    modalState.routines.map((routine) =>
                      h(
                        "div",
                        { key: routine.id, className: "list-group-item px-0 py-3" },
                        h("h5", { className: "mb-2 fw-bold text-dark" }, routine.name),
                        routine.description
                          ? h("p", { className: "text-muted small mb-2" }, routine.description)
                          : null,
                        h(
                          "div",
                          { className: "bg-light rounded-3 p-3 mt-2" },
                          routine.steps && routine.steps.length > 0
                            ? routine.steps.map((step, idx) =>
                                h(
                                  "div",
                                  { key: `${routine.id}-${idx}`, className: "d-flex align-items-center mb-2 last-mb-0" },
                                  h(
                                    "span",
                                    { className: "badge bg-white text-dark border me-3", style: { minWidth: "60px" } },
                                    step.time
                                  ),
                                  h(
                                    "div",
                                    null,
                                    h("div", { className: "fw-medium text-dark" }, step.name),
                                    h(
                                      "span",
                                      {
                                        className: "badge bg-secondary bg-opacity-10 text-secondary",
                                        style: { fontSize: "0.7rem" },
                                      },
                                      step.category
                                    )
                                  )
                                )
                              )
                            : h("div", { className: "text-muted small fst-italic" }, "ステップなし")
                        )
                      )
                    )
                  )
        )
      )
    )
  );
}

function CalendarPage({ dayLinkBase, showModal, showSampleButton, basePath, refreshToken }) {
  const searchParams = new URLSearchParams(window.location.search);
  const yearParam = parseInt(searchParams.get("year"), 10);
  const monthParam = parseInt(searchParams.get("month"), 10);

  const [modalState, setModalState] = useState({
    loading: false,
    error: null,
    routines: [],
    title: "曜日別ルーチン",
  });
  const modalRef = useRef(null);

  const { data, error } = useCalendarData(yearParam, monthParam, refreshToken);

  const handleDayHeaderClick = async (weekday) => {
    if (!showModal || !modalRef.current) return;
    const dayName = DAY_NAMES[weekday];
    setModalState({ loading: true, error: null, routines: [], title: `${dayName}曜日の登録ルーチン` });
    const modal = bootstrap.Modal.getInstance(modalRef.current) || new bootstrap.Modal(modalRef.current);
    modal.show();
    try {
      const res = await fetchJson(`/api/routines/day/${weekday}`);
      setModalState({
        loading: false,
        error: null,
        routines: Array.isArray(res.routines) ? res.routines : [],
        title: `${dayName}曜日の登録ルーチン`,
      });
    } catch (err) {
      setModalState({
        loading: false,
        error: err.message,
        routines: [],
        title: `${dayName}曜日の登録ルーチン`,
      });
    }
  };

  const handleSampleData = async () => {
    if (!confirm("明日と明後日のサンプルデータを追加しますか？\n（既存のデータは削除されません）")) {
      return;
    }
    try {
      const res = await fetchJson("/api/add_sample_data", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      alert(`サンプルデータが追加されました！\n${res.message}`);
      window.location.reload();
    } catch (err) {
      console.error("サンプルデータの追加に失敗しました:", err);
      alert(`サンプルデータの追加に失敗しました: ${err.message}`);
    }
  };

  if (error) {
    return h("div", { className: "alert alert-danger" }, "データの取得に失敗しました。");
  }
  if (!data) return null;

  const { prevMonth, prevYear, nextMonth, nextYear } = getMonthNav(data.year, data.month);
  const prevUrl = withPrefix(`${basePath}?year=${prevYear}&month=${prevMonth}`);
  const nextUrl = withPrefix(`${basePath}?year=${nextYear}&month=${nextMonth}`);

  return h(
    Fragment,
    null,
    h(
      "div",
      { className: "d-flex justify-content-between align-items-center mb-4" },
      h(
        "div",
        null,
        h("h2", { className: "mb-0" }, `${data.year}年 ${data.month}月`),
        h("p", { className: "text-muted" }, "ルーチンの概要")
      ),
      h(
        "div",
        { className: "btn-group shadow-sm", role: "group" },
        h("a", { href: prevUrl, className: "btn btn-light border" }, h("i", { className: "bi bi-chevron-left" })),
        h("a", { href: nextUrl, className: "btn btn-light border" }, h("i", { className: "bi bi-chevron-right" }))
      )
    ),
    h(
      "div",
      { className: "calendar-header" },
      DAY_NAMES.map((name, idx) =>
        h(
          "div",
          {
            key: name,
            onClick: showModal ? () => handleDayHeaderClick(idx) : undefined,
            style: showModal ? { cursor: "pointer" } : undefined,
            title: showModal ? `${name}曜日のルーチンを確認` : undefined,
            className: idx === 6 ? "text-danger" : undefined,
          },
          name
        )
      )
    ),
    h(CalendarGrid, { calendarData: data.calendar_data, today: data.today, dayLinkBase }),
    showSampleButton
      ? h(
          "div",
          { className: "d-flex justify-content-end mb-3" },
          h(
            "button",
            { id: "addSampleDataButton", className: "btn btn-secondary btn-sm", onClick: handleSampleData },
            "サンプルデータ追加 (明日・明後日)"
          )
        )
      : null,
    showModal ? h(DayRoutinesModal, { modalRef, modalState }) : null
  );
}

function DayPage({ dateStr, isStandalone, refreshToken, refreshIds, basePath }) {
  const { data, error } = useDayData(dateStr, refreshToken);
  const [routines, setRoutines] = useState([]);

  useEffect(() => {
    let isActive = true;
    const load = async () => {
      if (!data || typeof data.weekday !== "number") {
        setRoutines([]);
        return;
      }
      try {
        const res = await fetchJson(`/api/routines/day/${data.weekday}`);
        if (!isActive) return;
        setRoutines(Array.isArray(res.routines) ? res.routines : []);
      } catch (err) {
        if (!isActive) return;
        setRoutines([]);
      }
    };
    load();
    return () => {
      isActive = false;
    };
  }, [data, refreshToken]);

  useEffect(() => {
    if (!data || !refreshIds || refreshIds.length === 0) return;
    setTimeout(() => highlightIds(refreshIds), 50);
  }, [data, refreshIds, refreshToken]);

  if (error) {
    return h("div", { className: "alert alert-danger" }, "データの取得に失敗しました。");
  }
  if (!data) return null;

  const backUrl = withPrefix(basePath || "/");
  const formAction = withPrefix(stripPrefixFromPath(window.location.pathname || "/"));

  return h(
    Fragment,
    null,
    h(
      "div",
      { className: "mb-4" },
      h(
        "a",
        { href: backUrl, className: "text-decoration-none text-muted hover-primary" },
        h("i", { className: "bi bi-arrow-left me-1" }),
        " ",
        "カレンダーに戻る"
      )
    ),
    h(
      "div",
      { className: "row justify-content-center" },
      h(
        "div",
        { className: isStandalone ? "col-lg-12" : "col-lg-8" },
        h(
          "div",
          { className: "card shadow-sm border-0 mb-4" },
          h(
            "div",
            { className: "card-body" },
            h("h6", { className: "text-muted mb-3" }, "個別タスクを追加"),
            h(
              "form",
              { method: "POST", className: "row g-2 align-items-end", action: formAction },
              h(
                "div",
                { className: "col-7" },
                h("input", {
                  type: "text",
                  className: "form-control",
                  name: "custom_name",
                  placeholder: "タスク名",
                  required: true,
                })
              ),
              h(
                "div",
                { className: "col-3" },
                h("input", {
                  type: "time",
                  className: "form-control",
                  name: "custom_time",
                  defaultValue: "09:00",
                })
              ),
              h(
                "div",
                { className: "col-2" },
                h(
                  "button",
                  { type: "submit", name: "add_custom_task", className: "btn btn-outline-primary w-100" },
                  h("i", { className: "bi bi-plus-lg" })
                )
              )
            )
          )
        ),
        h(
          "div",
          { id: "schedule-container", className: "card shadow-md border-0 mb-4" },
          h(
            "div",
            { className: "card-header bg-white border-0 pt-4 pb-2 px-4" },
            h(
              "div",
              { className: "d-flex justify-content-between align-items-end" },
              h(
                "div",
                null,
                h("h6", { className: "text-uppercase text-muted mb-1" }, data.day_name),
                h("h2", { className: "mb-0 display-6 fw-bold" }, data.date_display)
              ),
              h(
                "div",
                { className: "text-end" },
                data.timeline_items.length > 0
                  ? h(
                      Fragment,
                      null,
                      h("div", { className: "display-6 fw-bold text-primary" }, `${data.completion_rate}%`),
                      h("small", { className: "text-muted" }, "完了率")
                    )
                  : null
              )
            )
          ),
          h(
            "div",
            { className: "card-body px-4 pt-2" },
            h("hr", { className: "mb-5 mt-2 opacity-10" }),
            data.timeline_items.length === 0
              ? h(
                  "div",
                  { className: "text-center py-5" },
                  h("div", { className: "mb-3 text-muted display-1" }, h("i", { className: "bi bi-calendar-check" })),
                  h("h4", { className: "text-muted" }, "タスクがありません。"),
                  h("p", { className: "text-muted" }, "上のフォームからタスクを追加してください。")
                )
              : h(
                  "form",
                  { method: "POST", action: formAction },
                  h(
                    "div",
                    { className: "timeline" },
                    data.timeline_items.map((item) => {
                      const doneName = item.type === "routine" ? `done_${item.id}` : `custom_done_${item.id}`;
                      const memoName = item.type === "routine" ? `memo_${item.id}` : `custom_memo_${item.id}`;
                      const isDone = item.is_done;
                      const memoVal = item.log_memo || "";
                      const itemDomId = `item_${item.type}_${item.id}`;

                      return h(
                        "div",
                        { key: itemDomId, className: "timeline-item", id: itemDomId },
                        h("div", {
                          className: "timeline-dot",
                          style: item.type === "custom" ? { borderColor: "var(--secondary-color)" } : undefined,
                        }),
                        h("div", { className: "timeline-time" }, item.time),
                        h(
                          "div",
                          { className: `card ${isDone ? "bg-light border-success" : ""}` },
                          h(
                            "div",
                            { className: "card-body" },
                            h(
                              "div",
                              { className: "d-flex justify-content-between align-items-start mb-2" },
                              h(
                                "div",
                                null,
                                item.type === "routine"
                                  ? h(
                                      Fragment,
                                      null,
                                      h(
                                        "span",
                                        { className: `badge badge-${item.step_category.toLowerCase()} mb-2` },
                                        item.step_category
                                      ),
                                      h("h5", { className: "card-title mb-1" }, item.step_name),
                                      h(
                                        "small",
                                        { className: "text-muted" },
                                        h("i", { className: "bi bi-collection me-1" }),
                                        item.routine_name
                                      )
                                    )
                                  : h(
                                      Fragment,
                                      null,
                                      h(
                                        "div",
                                        { className: "d-flex align-items-center mb-2" },
                                        h("span", { className: "badge bg-secondary me-2" }, "個人"),
                                        h(
                                          "button",
                                          {
                                            type: "submit",
                                            name: "delete_custom_task",
                                            value: item.id,
                                            className: "btn btn-link p-0 text-danger opacity-50 hover-opacity-100",
                                            style: { fontSize: "1rem" },
                                            title: "タスクを削除",
                                            onClick: (e) => {
                                              if (!confirm("このタスクを削除しますか？")) {
                                                e.preventDefault();
                                              }
                                            },
                                          },
                                          h("i", { className: "bi bi-trash" })
                                        )
                                      ),
                                      h("h5", { className: "card-title mb-1" }, item.step_name),
                                      h(
                                        "small",
                                        { className: "text-muted" },
                                        h("i", { className: "bi bi-person me-1" }),
                                        "一時的"
                                      )
                                    )
                              ),
                              h(
                                "div",
                                { className: "form-check form-switch" },
                                h("input", {
                                  className: "form-check-input fs-4",
                                  type: "checkbox",
                                  name: doneName,
                                  id: doneName,
                                  role: "switch",
                                  defaultChecked: !!isDone,
                                })
                              )
                            ),
                            h(
                              "div",
                              { className: "mt-3" },
                              h("input", {
                                type: "text",
                                className: "form-control form-control-sm bg-white",
                                name: memoName,
                                placeholder: "メモを追加...",
                                defaultValue: memoVal,
                              })
                            )
                          )
                        )
                      );
                    })
                  ),
                  h(
                    "div",
                    { className: "sticky-bottom bg-white py-3 border-top mt-4", style: { bottom: 0, zIndex: 10 } },
                    h(
                      "button",
                      { type: "submit", className: "btn btn-primary w-100 btn-lg shadow-sm" },
                      h("i", { className: "bi bi-save me-2" }),
                      "進捗を保存"
                    )
                  )
                )
          )
        ),
        h(
          "div",
          { className: "card shadow-sm border-0 mb-4" },
          h(
            "div",
            { className: "card-header bg-white border-0 pt-4 px-4" },
            h("h6", { className: "text-uppercase text-muted mb-1" }, "Registered Routines"),
            h("h5", { className: "fw-bold mb-0" }, "本日の登録ルーチン")
          ),
          h(
            "div",
            { className: "card-body px-4" },
            routines.length > 0
              ? h(
                  "div",
                  { className: "list-group list-group-flush" },
                  routines.map((routine) =>
                    h(
                      "div",
                      { key: routine.id, className: "list-group-item px-0 py-3 border-light" },
                      h(
                        "div",
                        { className: "d-flex justify-content-between align-items-center mb-2" },
                        h(
                          "h6",
                          { className: "mb-0 fw-bold text-dark" },
                          h("i", { className: "bi bi-repeat me-2 text-primary" }),
                          routine.name
                        ),
                        h("span", { className: "badge bg-light text-secondary border" }, `${routine.steps.length} Steps`)
                      ),
                      routine.description
                        ? h("p", { className: "small text-muted mb-2 ps-4" }, routine.description)
                        : null,
                      h(
                        "div",
                        { className: "bg-light bg-opacity-50 rounded-3 p-3 mt-2 ms-4" },
                        routine.steps.length === 0
                          ? h("span", { className: "small text-muted" }, "ステップなし")
                          : routine.steps
                              .slice()
                              .sort((a, b) => a.time.localeCompare(b.time))
                              .map((step) =>
                                h(
                                  "div",
                                  { key: step.id, className: "d-flex small text-secondary mb-1 align-items-center" },
                                  h(
                                    "span",
                                    {
                                      className: "fw-medium text-dark me-2 font-monospace",
                                      style: { minWidth: "45px" },
                                    },
                                    step.time
                                  ),
                                  h("span", { className: "me-auto" }, step.name),
                                  h(
                                    "span",
                                    {
                                      className: "badge bg-white text-muted border ms-2",
                                      style: { fontSize: "0.65rem" },
                                    },
                                    step.category
                                  )
                                )
                              )
                      )
                    )
                  )
                )
              : h(
                  "div",
                  { className: "text-center py-4" },
                  h("p", { className: "text-muted mb-0" }, "本日の登録ルーチンはありません。")
                )
          )
        ),
        h(
          "div",
          { id: "daily-log-wrapper" },
          h(
            "div",
            { className: "card shadow-sm border-0 mb-5", id: "daily-log-card" },
            h(
              "div",
              { className: "card-header bg-white border-0 pt-4 px-4" },
              h("h5", { className: "mb-0" }, h("i", { className: "bi bi-journal-text me-2" }), "日報"),
              h("small", { className: "text-muted" }, "今日の記録・感想")
            ),
            h(
              "div",
              { className: "card-body px-4" },
              h(
                "form",
                { method: "POST", action: formAction },
                h("textarea", {
                  className: "form-control mb-3",
                  name: "day_log_content",
                  rows: 5,
                  placeholder: "今日はどんな一日でしたか？",
                  defaultValue: data.day_log_content || "",
                }),
                h(
                  "div",
                  { className: "text-end" },
                  h(
                    "button",
                    { type: "submit", name: "save_log", className: "btn btn-secondary" },
                    h("i", { className: "bi bi-save me-2" }),
                    "ログを保存"
                  )
                )
              )
            )
          )
        )
      )
    )
  );
}

function RoutinesPage({ refreshToken }) {
  const [routines, setRoutines] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    let isActive = true;
    const load = async () => {
      try {
        const data = await fetchJson("/api/routines");
        if (!isActive) return;
        setRoutines(Array.isArray(data.routines) ? data.routines : []);
        setError(null);
      } catch (err) {
        if (!isActive) return;
        setError(err.message);
      }
    };
    load();
    return () => {
      isActive = false;
    };
  }, [refreshToken]);

  if (error) {
    return h("div", { className: "alert alert-danger" }, "データの取得に失敗しました。");
  }

  return h(
    "div",
    { className: "row" },
    h(
      "div",
      { className: "col-lg-4 mb-4" },
      h(
        "div",
        { className: "card shadow-md sticky-top", style: { top: "100px", zIndex: 1 } },
        h(
          "div",
          { className: "card-header bg-white border-0 pt-4 px-4" },
          h(
            "h5",
            { className: "mb-0 fw-bold text-primary" },
            h("i", { className: "bi bi-plus-circle me-2" }),
            "ルーチン作成"
          )
        ),
        h(
          "div",
          { className: "card-body px-4 pb-4" },
          h(
            "form",
            { action: withPrefix("/routines/add"), method: "POST" },
            h(
              "div",
              { className: "mb-3" },
              h("label", { className: "form-label small fw-bold text-muted" }, "ルーチン名"),
              h("input", {
                type: "text",
                name: "name",
                className: "form-control",
                required: true,
                placeholder: "例：朝のルーチン",
              })
            ),
            h(
              "div",
              { className: "mb-3" },
              h("label", { className: "form-label small fw-bold text-muted" }, "説明"),
              h("textarea", {
                name: "description",
                className: "form-control",
                rows: 2,
                placeholder: "説明（任意）...",
              })
            ),
            h(
              "div",
              { className: "mb-4" },
              h("label", { className: "form-label small fw-bold text-muted" }, "頻度（曜日）"),
              h(
                "div",
                { className: "d-flex flex-wrap gap-2" },
                DAY_NAMES.map((day, idx) =>
                  h(
                    Fragment,
                    { key: day },
                    h("input", {
                      type: "checkbox",
                      className: "btn-check",
                      name: "days",
                      value: idx,
                      id: `day${idx}`,
                      defaultChecked: true,
                      autoComplete: "off",
                    }),
                    h(
                      "label",
                      { className: "btn btn-outline-primary btn-sm rounded-pill", htmlFor: `day${idx}` },
                      day
                    )
                  )
                )
              )
            ),
            h("button", { type: "submit", className: "btn btn-primary w-100" }, "ルーチン作成")
          )
        )
      )
    ),
    h(
      "div",
      { className: "col-lg-8" },
      h(
        "div",
        { className: "d-flex justify-content-between align-items-center mb-4" },
        h("h3", { className: "mb-0 fw-bold" }, "マイルーチン"),
        h(
          "span",
          { className: "badge bg-white text-muted border shadow-sm" },
          `${routines.length} 件のルーチン`
        )
      ),
      routines.length === 0
        ? h(
            "div",
            { className: "text-center py-5 bg-white rounded-3 shadow-sm border border-dashed" },
            h("div", { className: "text-muted display-4 mb-3" }, h("i", { className: "bi bi-list-task" })),
            h("h5", { className: "text-muted" }, "ルーチンが見つかりません。"),
            h("p", { className: "text-muted small" }, "左のフォームから最初のルーチンを作成してください。")
          )
        : null,
      routines.map((routine) =>
        h(
          "div",
          { key: routine.id, className: "card mb-4 shadow-sm border-0" },
          h(
            "div",
            { className: "card-header bg-white border-bottom d-flex justify-content-between align-items-center py-3" },
            h(
              "div",
              null,
              h("h5", { className: "mb-1 fw-bold text-dark" }, routine.name),
              h("p", { className: "mb-0 text-muted small" }, routine.description || "")
            ),
            h(
              "form",
              {
                action: withPrefix(`/routines/${routine.id}/delete`),
                method: "POST",
                onSubmit: (e) => {
                  if (!confirm("本当にこのルーチンを削除しますか？")) {
                    e.preventDefault();
                  }
                },
              },
              h(
                "button",
                {
                  type: "submit",
                  className: "btn btn-link text-danger p-0 text-decoration-none",
                  title: "ルーチンを削除",
                },
                h("i", { className: "bi bi-trash" })
              )
            )
          ),
          h(
            "div",
            { className: "card-body bg-light bg-opacity-25" },
            h("h6", { className: "small fw-bold text-uppercase text-muted mb-3" }, "ステップ順序"),
            routine.steps.length === 0
              ? h("div", { className: "text-center text-muted small fst-italic mb-3" }, "ステップがまだありません。")
              : h(
                  "div",
                  { className: "list-group list-group-flush rounded-3 shadow-sm mb-3 bg-white" },
                  routine.steps.map((step) =>
                    h(
                      "div",
                      {
                        key: step.id,
                        className: "list-group-item d-flex justify-content-between align-items-center p-3 border-light",
                      },
                      h(
                        "div",
                        { className: "d-flex align-items-center" },
                        h("span", { className: "fw-bold text-primary me-3", style: { minWidth: "60px" } }, step.time),
                        h(
                          "div",
                          null,
                          h("div", { className: "fw-medium" }, step.name),
                          h(
                            "span",
                            { className: `badge badge-${step.category.toLowerCase()} mt-1`, style: { fontSize: "0.7rem" } },
                            step.category
                          )
                        )
                      ),
                      h(
                        "form",
                        { action: withPrefix(`/steps/${step.id}/delete`), method: "POST" },
                        h(
                          "button",
                          {
                            type: "submit",
                            className: "btn btn-light btn-sm text-muted rounded-circle",
                            title: "ステップを削除",
                          },
                          h("i", { className: "bi bi-x-lg" })
                        )
                      )
                    )
                  )
                ),
            h(
              "div",
              { className: "card border-0 bg-white shadow-sm" },
              h(
                "div",
                { className: "card-body p-3" },
                h(
                  "h6",
                  { className: "card-title small fw-bold text-muted mb-2" },
                  h("i", { className: "bi bi-plus-lg me-1" }),
                  "ステップ追加"
                ),
                h(
                  "form",
                  {
                    action: withPrefix(`/routines/${routine.id}/step/add`),
                    method: "POST",
                    className: "row g-2 align-items-center",
                  },
                  h(
                    "div",
                    { className: "col-md-2" },
                    h("input", { type: "time", name: "time", className: "form-control form-control-sm", required: true })
                  ),
                  h(
                    "div",
                    { className: "col-md-5" },
                    h("input", {
                      type: "text",
                      name: "name",
                      className: "form-control form-control-sm",
                      placeholder: "ステップ名",
                      required: true,
                    })
                  ),
                  h(
                    "div",
                    { className: "col-md-3" },
                    h(
                      "select",
                      { name: "category", className: "form-select form-select-sm" },
                      h("option", { value: "Lifestyle" }, "Lifestyle"),
                      h("option", { value: "IoT" }, "IoT"),
                      h("option", { value: "Browser" }, "Browser"),
                      h("option", { value: "Other" }, "Other")
                    )
                  ),
                  h(
                    "div",
                    { className: "col-md-2 text-end" },
                    h("button", { type: "submit", className: "btn btn-primary btn-sm w-100" }, "追加")
                  )
                )
              )
            )
          ),
          h(
            "div",
            { className: "card-footer bg-white border-top-0 text-muted small py-2" },
            h("i", { className: "bi bi-calendar-week me-1" }),
            "曜日: ",
            routine.days
              .split(",")
              .map((d) => ({
                key: d,
                label: { "0": "月", "1": "火", "2": "水", "3": "木", "4": "金", "5": "土", "6": "日" }[d],
              }))
              .map((day) => h("span", { key: day.key, className: "me-1" }, day.label))
          )
        )
      )
    )
  );
}

function EvaluationPage({ currentModel }) {
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

  const [rows, setRows] = useState(
    scenarios.map((prompt) => ({
      prompt,
      loading: false,
      reply: null,
      toolsText: null,
      judgment: null,
      toolCalls: [],
    }))
  );
  const conversationRef = useRef([]);

  const refreshCalendarFrame = () => {
    const calFrame = document.getElementById("calendarFrame");
    if (calFrame && calFrame.contentWindow) {
      calFrame.contentWindow.location.reload();
    }
  };

  const runScenario = async (index) => {
    setRows((prev) =>
      prev.map((row, idx) => (idx === index ? { ...row, loading: true } : row))
    );

    const prompt = rows[index].prompt;
    const currentMessages = [...conversationRef.current, { role: "user", content: prompt }];
    const payloadMessages = currentMessages.slice(-10);

    try {
      const data = await fetchJson("/api/evaluation/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: payloadMessages }),
      });

      conversationRef.current = [...conversationRef.current, { role: "user", content: prompt }, { role: "assistant", content: data.reply }];

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
      setRows((prev) =>
        prev.map((row, idx) =>
          idx === index ? { ...row, loading: false, reply: `エラー: ${err.message}` } : row
        )
      );
    }
  };

  const logResult = async (index, isSuccess) => {
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
      alert(`ログ保存失敗: ${err.message}`);
    }
  };

  const handleSeed = async () => {
    if (!confirm("サンプルデータを追加しますか？（先週金曜の日報などが作成されます）")) return;
    try {
      const data = await fetchJson("/api/evaluation/seed", { method: "POST" });
      alert(data.message || data.error);
      refreshCalendarFrame();
    } catch (err) {
      alert(`エラー: ${err.message}`);
    }
  };

  const handleSeedPeriod = async () => {
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const dayAfter = new Date(today);
    dayAfter.setDate(dayAfter.getDate() + 2);
    const formatDate = (d) => d.toISOString().split("T")[0];
    const startDate = formatDate(tomorrow);
    const endDate = formatDate(dayAfter);

    if (!confirm(`明日(${startDate})から明後日(${endDate})にサンプル予定を追加しますか？`)) return;
    try {
      const data = await fetchJson("/api/evaluation/seed_period", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start_date: startDate, end_date: endDate }),
      });
      alert(data.message || data.error);
      refreshCalendarFrame();
    } catch (err) {
      alert(`エラー: ${err.message}`);
    }
  };

  const handleReset = async () => {
    if (!confirm("本当に全データを削除しますか？")) return;
    try {
      const data = await fetchJson("/api/evaluation/reset", { method: "POST" });
      conversationRef.current = [];
      alert(data.message || data.error);
    } catch (err) {
      alert(`エラー: ${err.message}`);
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
}

function FlashMessages({ messages }) {
  if (!messages || messages.length === 0) return null;
  return h(
    "div",
    { className: "alert alert-info border-0 shadow-sm rounded-3 mb-4" },
    messages.map((msg, idx) =>
      h(
        "div",
        { key: `${idx}-${msg}` },
        h("i", { className: "bi bi-info-circle me-2" }),
        msg
      )
    )
  );
}

function ChatSidebar({ onRefresh, onModelChange }) {
  const [modelOptions, setModelOptions] = useState([]);
  const [selectedModel, setSelectedModel] = useState(
    `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`
  );
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const [isPaused, setIsPaused] = useState(false);
  const [isSending, setIsSending] = useState(false);

  const historyRef = useRef([]);
  const baseUrlRef = useRef("");
  const skipNextModelUpdateRef = useRef(false);
  const logRef = useRef(null);
  const inputRef = useRef(null);

  const selectOptions = useMemo(() => {
    if (modelOptions.length > 0) return modelOptions;
    return [{ ...DEFAULT_MODEL, label: "GPT-OSS 20B (Groq)" }];
  }, [modelOptions]);

  const appendMessage = (role, content, timestamp) => {
    const timeDisplay = timestamp || nowTime();
    historyRef.current = [...historyRef.current, { role, content }];
    setMessages((prev) => [...prev, { role, content, timeDisplay }]);
  };

  const loadChatHistory = async () => {
    try {
      const data = await fetchJson("/api/chat/history");
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

  const updateModelSelection = async (value) => {
    const fallbackValue = `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`;
    const [providerRaw, modelRaw] = (value || fallbackValue).split(":");
    const provider = providerRaw || DEFAULT_MODEL.provider;
    const model = modelRaw || DEFAULT_MODEL.model;
    const payload = { provider, model, base_url: baseUrlRef.current || "" };

    try {
      const res = await fetchJson("/model_settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      onModelChange?.(`${res.applied.provider}:${res.applied.model}`);
    } catch (err) {
      console.error("Failed to update model:", err);
      alert(`モデルの更新に失敗しました: ${err.message}`);
    }
  };

  const loadModelOptions = async () => {
    let nextValue = `${DEFAULT_MODEL.provider}:${DEFAULT_MODEL.model}`;
    try {
      const data = await fetchJson("/api/models", { cache: "no-store" });
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

    return await fetchJson("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  };

  const handleSubmit = async (event) => {
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
      appendMessage("assistant", `エラーが発生しました: ${err.message}`);
    } finally {
      setIsSending(false);
    }
  };

  const handleReset = async () => {
    if (!confirm("チャット履歴を削除しますか？")) return;

    try {
      await fetchJson("/api/chat/history", { method: "DELETE" });
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
          h(
            "label",
            { htmlFor: "modelSelect", className: "sr-only" },
            "モデルを選択"
          ),
          h(
            "select",
            {
              id: "modelSelect",
              className: "model-selection__select",
              value: selectedModel,
              onChange: (e) => setSelectedModel(e.target.value),
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
          onChange: (e) => setInputValue(e.target.value),
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
}

function NavBar() {
  return h(
    "nav",
    { className: "navbar navbar-expand-lg fixed-top" },
    h(
      "div",
      { className: "container" },
      h(
        "a",
        { className: "navbar-brand", href: withPrefix("/") },
        h("i", { className: "bi bi-calendar-check me-2" }),
        "ルーチン・スケジューラー"
      ),
      h(
        "button",
        {
          className: "navbar-toggler",
          type: "button",
          "data-bs-toggle": "collapse",
          "data-bs-target": "#navbarNav",
        },
        h("span", { className: "navbar-toggler-icon" })
      ),
      h(
        "div",
        { className: "collapse navbar-collapse", id: "navbarNav" },
        h(
          "ul",
          { className: "navbar-nav ms-auto" },
          h(
            "li",
            { className: "nav-item" },
            h("a", { className: "nav-link", href: withPrefix("/") }, "カレンダー")
          ),
          h(
            "li",
            { className: "nav-item" },
            h("a", { className: "nav-link", href: withPrefix("/routines") }, "ルーチン設定")
          )
        )
      )
    )
  );
}

function MainShell({ children, onRefresh, flashMessages, onModelChange }) {
  return h(
    Fragment,
    null,
    h(NavBar),
    h(
      "div",
      { className: "app-shell" },
      h(ChatSidebar, { onRefresh, onModelChange }),
      h(
        "main",
        { className: "main" },
        h(
          "div",
          { className: "container main__container" },
          h(FlashMessages, { messages: flashMessages }),
          children
        )
      )
    )
  );
}

function StandaloneShell({ children }) {
  return h("div", { className: "standalone-container" }, children);
}

function EmbedShell({ yearTitle, nav, content }) {
  return h(
    "div",
    { className: "embed-shell" },
    h(
      "div",
      { className: "d-flex justify-content-between align-items-center embed-header" },
      h(
        "div",
        null,
        h("h2", { className: "mb-0" }, yearTitle || ""),
        h("p", { className: "text-muted mb-0" }, "Scheduler Agent")
      ),
      nav
    ),
    h("div", { className: "calendar-wrapper" }, content)
  );
}

function EmbedCalendarPage() {
  const searchParams = new URLSearchParams(window.location.search);
  const yearParam = parseInt(searchParams.get("year"), 10);
  const monthParam = parseInt(searchParams.get("month"), 10);
  const { data } = useCalendarData(yearParam, monthParam, 0);
  if (!data) return null;

  const { prevMonth, prevYear, nextMonth, nextYear } = getMonthNav(data.year, data.month);
  const prevUrl = withPrefix(`/embed/calendar?year=${prevYear}&month=${prevMonth}`);
  const nextUrl = withPrefix(`/embed/calendar?year=${nextYear}&month=${nextMonth}`);

  return h(EmbedShell, {
    yearTitle: `${data.year}年 ${data.month}月`,
    nav: h(
      "div",
      { className: "btn-group shadow-sm", role: "group" },
      h("a", { href: prevUrl, className: "btn btn-light border" }, h("i", { className: "bi bi-chevron-left" })),
      h("a", { href: nextUrl, className: "btn btn-light border" }, h("i", { className: "bi bi-chevron-right" }))
    ),
    content: h(
      Fragment,
      null,
      h(
        "div",
        { className: "calendar-header" },
        DAY_NAMES.map((name, idx) =>
          h("div", { key: name, className: idx === 6 ? "text-danger" : undefined }, name)
        )
      ),
      h(CalendarGrid, { calendarData: data.calendar_data, today: data.today, dayLinkBase: "/day/" })
    ),
  });
}

function App() {
  const path = stripPrefixFromPath(window.location.pathname || "/");
  const [refreshToken, setRefreshToken] = useState(0);
  const [refreshIds, setRefreshIds] = useState([]);
  const [flashMessages, setFlashMessages] = useState([]);
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
    fetchJson("/api/flash")
      .then((data) => setFlashMessages(Array.isArray(data.messages) ? data.messages : []))
      .catch(() => setFlashMessages([]));
  }, []);

  const handleRefresh = (ids) => {
    setRefreshIds(ids || []);
    setRefreshToken(Date.now());
  };

  let content = null;

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
    content = h("div", { className: "alert alert-warning" }, "ページが見つかりません。")
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
}

const rootEl = document.getElementById("app-root");
if (rootEl) {
  const root = createRoot(rootEl);
  if (typeof flushSync === "function") {
    flushSync(() => {
      root.render(h(App));
    });
  } else {
    root.render(h(App));
  }
}
