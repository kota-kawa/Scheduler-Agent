import { useEffect, useState } from "react";
import { fetchJson } from "../api/client";
import type { DayResponse } from "../types/api";

interface DayState {
  loading: boolean;
  data: DayResponse | null;
  error: string | null;
}

export const useDayData = (dateStr: string, refreshToken: number): DayState => {
  const [state, setState] = useState<DayState>({ loading: true, data: null, error: null });

  useEffect(() => {
    let isActive = true;
    const load = async () => {
      if (!dateStr) {
        setState({ loading: false, data: null, error: "Invalid date" });
        return;
      }
      setState({ loading: true, data: state.data, error: null });
      try {
        const data = await fetchJson<DayResponse>(`/api/day/${dateStr}`);
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
  }, [dateStr, refreshToken]);

  return state;
};
