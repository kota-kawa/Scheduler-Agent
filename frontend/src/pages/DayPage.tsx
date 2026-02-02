import React, { Fragment, useEffect, useState } from "react";
import { fetchJson, stripPrefixFromPath, withPrefix } from "../api/client";
import { useDayData } from "../hooks/useDayData";
import { highlightIds } from "../utils/dom";
import type { Routine, RoutinesResponse } from "../types/api";

const { createElement: h } = React;

interface DayPageProps {
  dateStr: string;
  isStandalone: boolean;
  refreshToken: number;
  refreshIds?: Array<string | number>;
  basePath: string;
}

export const DayPage = ({
  dateStr,
  isStandalone,
  refreshToken,
  refreshIds,
  basePath,
}: DayPageProps) => {
  const { data, error } = useDayData(dateStr, refreshToken);
  const [routines, setRoutines] = useState<Routine[]>([]);

  useEffect(() => {
    let isActive = true;
    const load = async () => {
      if (!data || typeof data.weekday !== "number") {
        setRoutines([]);
        return;
      }
      try {
        const res = await fetchJson<RoutinesResponse>(`/api/routines/day/${data.weekday}`);
        if (!isActive) return;
        setRoutines(Array.isArray(res.routines) ? res.routines : []);
      } catch {
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
                                            onClick: (e: React.MouseEvent<HTMLButtonElement>) => {
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
};
