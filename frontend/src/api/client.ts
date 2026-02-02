export class ApiError extends Error {
  status: number;
  detail?: string;

  constructor(message: string, status: number, detail?: string) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

const proxyPrefixMeta = document.querySelector("meta[name='proxy-prefix']");
const proxyPrefixRaw = (proxyPrefixMeta?.getAttribute("content") || "").trim();
const proxyPrefix = proxyPrefixRaw === "/" ? "" : proxyPrefixRaw.replace(/\/+$/, "");

export const withPrefix = (path = "/"): string => {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (!proxyPrefix) return normalized;
  const cleaned = proxyPrefix.startsWith("/") ? proxyPrefix : `/${proxyPrefix}`;
  return `${cleaned}${normalized}`.replace(/\/{2,}/g, "/");
};

export const stripPrefixFromPath = (path: string): string => {
  if (!proxyPrefix) return path || "/";
  const cleaned = proxyPrefix.startsWith("/") ? proxyPrefix : `/${proxyPrefix}`;
  if (path && path.startsWith(cleaned)) {
    const stripped = path.slice(cleaned.length);
    return stripped.startsWith("/") ? stripped : `/${stripped || ""}`;
  }
  return path || "/";
};

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
