export const DEFAULT_MODEL = {
  provider: "groq",
  model: "openai/gpt-oss-20b",
  base_url: "",
};

export const INITIAL_GREETING =
  "こんにちは！スケジューラーの確認やタスク登録をお手伝いします。やりたいことを日本語で教えてください。";

export const DAY_NAMES = ["月", "火", "水", "木", "金", "土", "日"] as const;
