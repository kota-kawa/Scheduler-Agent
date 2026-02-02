import { useEffect, useState } from "react";
import { fetchJson } from "../api/client";
import type { CalendarResponse } from "../types/api";

interface CalendarState {
  loading: boolean;
  data: CalendarResponse | null;
  error: string | null;
}

export const useCalendarData = (
  yearParam: number,
  monthParam: number,
  refreshToken: number
): CalendarState => {
  const [state, setState] = useState<CalendarState>({ loading: true, data: null, error: null });

  useEffect(() => {
    let isActive = true;
    const load = async () => {
      setState({ loading: true, data: state.data, error: null });
      try {
        const params = new URLSearchParams();
        if (yearParam) params.set("year", String(yearParam));
        if (monthParam) params.set("month", String(monthParam));
        const query = params.toString();
        const url = query ? `/api/calendar?${query}` : "/api/calendar";
        const data = await fetchJson<CalendarResponse>(url);
        if (!isActive) return;
        setState({ loading: false, data, error: null });
      } catch (err) {
        if (!isActive) return;
        const message = err instanceof Error ? err.message : "Unknown error";
        setState({ loading: false, data: null, error: message });
      }
    };
    load();
    return () => {
      isActive = false;
    };
  }, [yearParam, monthParam, refreshToken]);

  return state;
};
