import React from "react";
import { withPrefix } from "../api/client";
import type { CalendarWeek } from "../types/api";

const { createElement: h } = React;

// 日本語: カレンダーグリッドの props / English: Props for calendar grid
interface CalendarGridProps {
  calendarData: CalendarWeek[];
  today: string;
  dayLinkBase: string;
}

// 日本語: 月間カレンダーのグリッド表示 / English: Calendar grid renderer
export const CalendarGrid = ({ calendarData, today, dayLinkBase }: CalendarGridProps) => {
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
        // 日本語: 達成率に応じた表示 / English: Render based on completion ratio
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
              { className: "d-flex gap-1 align-items-center" },
              day.has_day_log
                ? h("i", { className: "bi bi-journal-text text-primary", title: "日報あり" })
                : null,
              day.routine_count > 0
                ? h("span", { className: "routine-indicator-dot", title: "ルーチンあり" })
                : null,
              day.total_steps > 0
                ? ratio === 1
                  ? h("i", { className: "bi bi-check-circle-fill text-success" })
                  : ratio > 0
                    ? h("i", { className: "bi bi-check-circle text-warning" })
                    : h("i", { className: "bi bi-circle text-muted" })
                : null
            )
          ),
          day.total_steps > 0
            ? h(
                "div",
                { className: "progress mt-2", style: { height: "6px" } },
                h("div", {
                  className: `progress-bar ${ratio === 1 ? "bg-success" : "bg-primary"}`,
                  style: { width: `${ratio * 100}%` },
                })
              )
            : null
        );
      })
    )
  );
};
