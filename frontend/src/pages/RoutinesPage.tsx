import React, { Fragment, useEffect, useState } from "react";
import { fetchJson, withPrefix } from "../api/client";
import { DAY_NAMES } from "../utils/constants";
import type { Routine, RoutinesResponse } from "../types/api";

const { createElement: h } = React;

interface RoutinesPageProps {
  refreshToken: number;
}

// 日本語: ルーチン管理ページ / English: Routines management page
export const RoutinesPage = ({ refreshToken }: RoutinesPageProps) => {
  // 日本語: ルーチン一覧の状態 / English: Routines list state
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 日本語: ルーチン一覧を取得 / English: Load routines list
    let isActive = true;
    const load = async () => {
      try {
        const data = await fetchJson<RoutinesResponse>("/api/routines");
        if (!isActive) return;
        setRoutines(Array.isArray(data.routines) ? data.routines : []);
        setError(null);
      } catch (err) {
        if (!isActive) return;
        const message = err instanceof Error ? err.message : "Unknown error";
        setError(message);
      }
    };
    load();
    return () => {
      isActive = false;
    };
  }, [refreshToken]);

  if (error) {
    // 日本語: 取得失敗時のエラー表示 / English: Show fetch error
    return h("div", { className: "alert alert-danger" }, "データの取得に失敗しました。");
  }

  // 日本語: 作成フォーム＋一覧を描画 / English: Render creation form and list
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
            h("p", { className: "text-muted small" }, "左側のフォームから新しいルーチンを作成してください。")
          )
        : routines.map((routine) =>
            h(
              "div",
              { key: routine.id, className: "card shadow-sm mb-4 border-0" },
              h(
                "div",
                { className: "card-body p-4" },
                h(
                  "div",
                  { className: "d-flex justify-content-between align-items-start" },
                  h(
                    "div",
                    null,
                    h(
                      "h5",
                      { className: "fw-bold mb-1 text-primary" },
                      h("i", { className: "bi bi-repeat me-2" }),
                      routine.name
                    ),
                    routine.description
                      ? h("p", { className: "text-muted small mb-2" }, routine.description)
                      : null
                  ),
                  h(
                    "form",
                    { action: withPrefix(`/routines/${routine.id}/delete`), method: "POST" },
                    h(
                      "button",
                      { className: "btn btn-outline-danger btn-sm", type: "submit" },
                      h("i", { className: "bi bi-trash" }),
                      " 削除"
                    )
                  )
                ),
                h(
                  "div",
                  { className: "mt-3" },
                  routine.steps.length > 0
                    ? routine.steps
                        .slice()
                        .sort((a, b) => a.time.localeCompare(b.time))
                        .map((step) =>
                          h(
                            "div",
                            { key: step.id, className: "row align-items-center mb-2" },
                            h(
                              "div",
                              { className: "col-md-3" },
                              h("span", { className: "badge bg-light text-secondary border" }, step.time)
                            ),
                            h(
                              "div",
                              { className: "col-md-5" },
                              h("span", { className: "fw-medium text-dark" }, step.name)
                            ),
                            h(
                              "div",
                              { className: "col-md-3" },
                              h("span", { className: "badge bg-secondary bg-opacity-10 text-secondary" }, step.category)
                            ),
                            h(
                              "div",
                              { className: "col-md-1 text-end" },
                              h(
                                "form",
                                { action: withPrefix(`/steps/${step.id}/delete`), method: "POST" },
                                h(
                                  "button",
                                  { type: "submit", className: "btn btn-link text-danger p-0" },
                                  h("i", { className: "bi bi-x-lg" })
                                )
                              )
                            )
                          )
                        )
                    : h("p", { className: "text-muted small mb-0" }, "ステップがありません。")
                )
              ),
              h("hr", { className: "my-0" }),
              h(
                "div",
                { className: "card-body p-4" },
                h("h6", { className: "text-muted mb-3" }, "ステップを追加"),
                h(
                  "form",
                  { action: withPrefix(`/routines/${routine.id}/step/add`), method: "POST" },
                  h(
                    "div",
                    { className: "row g-2 align-items-end" },
                    h(
                      "div",
                      { className: "col-md-4" },
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
                      h("input", {
                        type: "time",
                        name: "time",
                        className: "form-control form-control-sm",
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
};
