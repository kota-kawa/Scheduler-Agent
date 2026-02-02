import React, { Fragment, useRef, useState } from "react";
import { fetchJson, withPrefix } from "../api/client";
import { CalendarGrid } from "../components/CalendarGrid";
import { useCalendarData } from "../hooks/useCalendarData";
import { DAY_NAMES } from "../utils/constants";
import { getMonthNav } from "../utils/time";
import type { RoutinesResponse, Routine, SampleDataResponse } from "../types/api";

const { createElement: h } = React;

interface ModalState {
  loading: boolean;
  error: string | null;
  routines: Routine[];
  title: string;
}

interface DayRoutinesModalProps {
  modalRef: React.RefObject<HTMLDivElement | null>;
  modalState: ModalState;
}

const DayRoutinesModal = ({ modalRef, modalState }: DayRoutinesModalProps) =>
  h(
    "div",
    { className: "modal fade", tabIndex: -1, ref: modalRef },
    h(
      "div",
      { className: "modal-dialog modal-dialog-centered modal-dialog-scrollable" },
      h(
        "div",
        { className: "modal-content shadow-sm border-0" },
        h(
          "div",
          { className: "modal-header border-0" },
          h("h5", { className: "modal-title" }, modalState.title),
          h("button", { type: "button", className: "btn-close", "data-bs-dismiss": "modal" })
        ),
        h(
          "div",
          { className: "modal-body" },
          modalState.loading
            ? h("div", { className: "text-center text-muted py-5" }, "読み込み中...")
            : modalState.error
              ? h("div", { className: "alert alert-danger" }, "データ取得に失敗しました。")
              : modalState.routines.length === 0
                ? h(
                    "div",
                    { className: "text-center text-muted py-5" },
                    h("i", { className: "bi bi-inbox mb-2 d-block fs-2" }),
                    "ルーチンが登録されていません"
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
        ),
        h(
          "div",
          { className: "modal-footer border-0" },
          h("button", { type: "button", className: "btn btn-secondary", "data-bs-dismiss": "modal" }, "閉じる")
        )
      )
    )
  );

interface CalendarPageProps {
  dayLinkBase: string;
  showModal: boolean;
  showSampleButton: boolean;
  basePath: string;
  refreshToken: number;
}

export const CalendarPage = ({
  dayLinkBase,
  showModal,
  showSampleButton,
  basePath,
  refreshToken,
}: CalendarPageProps) => {
  const searchParams = new URLSearchParams(window.location.search);
  const yearParam = Number.parseInt(searchParams.get("year") || "", 10);
  const monthParam = Number.parseInt(searchParams.get("month") || "", 10);

  const [modalState, setModalState] = useState<ModalState>({
    loading: false,
    error: null,
    routines: [],
    title: "曜日別ルーチン",
  });
  const modalRef = useRef<HTMLDivElement | null>(null);

  const { data, error } = useCalendarData(yearParam, monthParam, refreshToken);

  const handleDayHeaderClick = async (weekday: number) => {
    if (!showModal || !modalRef.current) return;
    const dayName = DAY_NAMES[weekday];
    setModalState({ loading: true, error: null, routines: [], title: `${dayName}曜日の登録ルーチン` });
    const modal = bootstrap.Modal.getInstance(modalRef.current) || new bootstrap.Modal(modalRef.current);
    modal.show();
    try {
      const res = await fetchJson<RoutinesResponse>(`/api/routines/day/${weekday}`);
      setModalState({
        loading: false,
        error: null,
        routines: Array.isArray(res.routines) ? res.routines : [],
        title: `${dayName}曜日の登録ルーチン`,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      setModalState({
        loading: false,
        error: message,
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
      const res = await fetchJson<SampleDataResponse>("/api/add_sample_data", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      alert(`サンプルデータが追加されました！\n${res.message}`);
      window.location.reload();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      console.error("サンプルデータの追加に失敗しました:", err);
      alert(`サンプルデータの追加に失敗しました: ${message}`);
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
};
