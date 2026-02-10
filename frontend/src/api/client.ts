// 日本語: API エラーを表す例外クラス / English: Error class for API failures
export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

// 日本語: 逆プロキシ用の prefix を meta から取得 / English: Read reverse-proxy prefix from meta tag
const proxyPrefixMeta = document.querySelector("meta[name='proxy-prefix']");
const proxyPrefixRaw = (proxyPrefixMeta?.getAttribute("content") || "").trim();
const proxyPrefix = proxyPrefixRaw === "/" ? "" : proxyPrefixRaw.replace(/\/+$/, "");

// 日本語: prefix を URL パスへ付与 / English: Add prefix to a path
export const withPrefix = (path = "/"): string => {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (!proxyPrefix) return normalized;
  const cleaned = proxyPrefix.startsWith("/") ? proxyPrefix : `/${proxyPrefix}`;
  return `${cleaned}${normalized}`.replace(/\/{2,}/g, "/");
};

// 日本語: 現在パスから prefix を除去 / English: Remove prefix from current path
export const stripPrefixFromPath = (path: string): string => {
  if (!proxyPrefix) return path || "/";
  const cleaned = proxyPrefix.startsWith("/") ? proxyPrefix : `/${proxyPrefix}`;
  if (path && path.startsWith(cleaned)) {
    const stripped = path.slice(cleaned.length);
    return stripped.startsWith("/") ? stripped : `/${stripped || ""}`;
  }
  return path || "/";
};

// 日本語: JSON レスポンス用の fetch ラッパー / English: fetch wrapper for JSON responses
export const fetchJson = async <T>(path: string, options?: RequestInit): Promise<T> => {
  const res = await fetch(withPrefix(path), options);
  if (!res.ok) {
    const errText = await res.text();
    throw new ApiError(errText || `HTTP ${res.status}`, res.status);
  }
  const contentType = res.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new ApiError("Response is not JSON", res.status);
  }
  return (await res.json()) as T;
};
