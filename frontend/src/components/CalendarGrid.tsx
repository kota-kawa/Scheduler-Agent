import React from "react";
import { withPrefix } from "../api/client";
import type { CalendarWeek } from "../types/api";

const { createElement: h } = React;

interface CalendarGridProps {
  calendarData: CalendarWeek[];
  today: string;
  dayLinkBase: string;
}

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
            : null,
          day.total_routines === 0 && !day.has_day_log
            ? h("div", { className: "text-muted small mt-2" }, "予定なし")
            : null
        );
      })
    )
  );
};
