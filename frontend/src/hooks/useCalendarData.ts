import { useEffect, useState } from "react";
import { fetchJson } from "../api/client";
import type { CalendarResponse } from "../types/api";

// 日本語: カレンダーデータ取得の状態 / English: State for calendar data fetching
interface CalendarState {
  loading: boolean;
  data: CalendarResponse | null;
  error: string | null;
}

// 日本語: 月間カレンダーを取得するカスタムフック / English: Hook to fetch monthly calendar data
export const useCalendarData = (
  yearParam: number,
  monthParam: number,
  refreshToken: number
): CalendarState => {
  const [state, setState] = useState<CalendarState>({ loading: true, data: null, error: null });

  useEffect(() => {
    // 日本語: パラメータ/更新トークン変更時に再取得 / English: Reload when params or refresh token change
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
