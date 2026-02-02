export type ChatRole = "system" | "user" | "assistant";

export interface CalendarDay {
  date: string;
  day_num: number;
  is_current_month: boolean;
  total_routines: number;
  total_steps: number;
  completed_steps: number;
  has_day_log: boolean;
}

export type CalendarWeek = CalendarDay[];

export interface CalendarResponse {
  calendar_data: CalendarWeek[];
  year: number;
  month: number;
  today: string;
}

export interface RoutineStep {
  id: number;
  name: string;
  time: string;
  category: string;
}

export interface Routine {
  id: number;
  name: string;
  description?: string | null;
  days: string;
  steps: RoutineStep[];
}

export interface RoutinesResponse {
  routines: Routine[];
}

export interface DayTimelineItem {
  type: "routine" | "custom";
  time: string;
  id: number;
  routine_name: string;
  step_name: string;
  step_category: string;
  log_done: boolean;
  log_memo: string | null;
  is_done: boolean;
}

export interface DayResponse {
  date: string;
  weekday: number;
  day_name: string;
  date_display: string;
  timeline_items: DayTimelineItem[];
  completion_rate: number;
  day_log_content: string | null;
}

export interface FlashResponse {
  messages: string[];
}

export interface ChatHistoryItem {
  role: ChatRole;
  content: string;
  timestamp: string;
}

export interface ChatHistoryResponse {
  history: ChatHistoryItem[];
}

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
}

export interface ChatResponse {
  reply?: string;
  should_refresh?: boolean;
  modified_ids?: string[];
}

export interface ModelOption {
  provider: string;
  model: string;
  base_url?: string;
  label?: string;
}

export interface ModelsResponse {
  models: ModelOption[];
  current: {
    provider: string;
    model: string;
    base_url: string;
  };
}

export interface ModelSettingsResponse {
  status: "ok";
  applied: {
    provider: string;
    model: string;
    base_url: string;
  };
}

export interface EvaluationChatResponse {
  reply: string;
  actions?: Record<string, unknown>[];
  results?: string[];
  errors?: string[];
}

export interface EvaluationSeedResponse {
  message?: string;
  error?: string;
}

export interface SampleDataResponse {
  message?: string;
}
