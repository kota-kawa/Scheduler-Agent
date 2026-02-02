import React, { Fragment } from "react";
import { withPrefix } from "../api/client";
import { CalendarGrid } from "../components/CalendarGrid";
import { EmbedShell } from "../components/Shells";
import { useCalendarData } from "../hooks/useCalendarData";
import { DAY_NAMES } from "../utils/constants";
import { getMonthNav } from "../utils/time";

const { createElement: h } = React;

export const EmbedCalendarPage = () => {
  const searchParams = new URLSearchParams(window.location.search);
  const yearParam = Number.parseInt(searchParams.get("year") || "", 10);
  const monthParam = Number.parseInt(searchParams.get("month") || "", 10);
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
};
