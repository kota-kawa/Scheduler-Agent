import type { ChatRole, ModelOption } from "./api";

export interface ChatDisplayMessage {
  role: ChatRole;
  content: string;
  timeDisplay: string;
  executionLog?: string;
}

export interface ModelSelectionOption extends ModelOption {
  label?: string;
}

export interface EvaluationRow {
  prompt: string;
  loading: boolean;
  reply: string | null;
  toolsText: string | null;
  judgment: "OK" | "NG" | null;
  toolCalls: Record<string, unknown>[];
}
