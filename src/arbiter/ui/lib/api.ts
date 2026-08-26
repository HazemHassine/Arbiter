const API_ROOT = "/api/v1";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const direct = path === "/health" || path.startsWith("/api/") || path.startsWith("/.");
  const url = direct ? path : `${API_ROOT}${path.startsWith("/") ? path : `/${path}`}`;
  const response = await fetch(url, {
    ...init,
    cache: "no-store",
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...init.headers,
    },
  });
  const contentType = response.headers.get("content-type") ?? "";
  const body: unknown = contentType.includes("json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? String((body as { detail: unknown }).detail)
        : `Request failed (${response.status})`;
    throw new ApiError(detail, response.status, body);
  }
  return body as T;
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
}

export function remove<T>(path: string): Promise<T> {
  return api<T>(path, { method: "DELETE" });
}

export function eventStreamUrl(): string {
  return `${API_ROOT}/events/stream`;
}

export async function streamJsonLines<T>(
  path: string,
  body: unknown,
  onEvent: (event: T) => void,
  signal?: AbortSignal,
): Promise<void> {
  const url = `${API_ROOT}${path.startsWith("/") ? path : `/${path}`}`;
  const response = await fetch(url, {
    method: "POST",
    body: JSON.stringify(body),
    cache: "no-store",
    headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
    signal,
  });
  if (!response.ok) {
    const text = await response.text();
    let responseBody: unknown = text;
    try { responseBody = JSON.parse(text) as unknown; } catch { /* Keep the plain-text error body. */ }
    const detail =
      responseBody && typeof responseBody === "object" && "detail" in responseBody
        ? String((responseBody as { detail: unknown }).detail)
        : `Request failed (${response.status})`;
    throw new ApiError(detail, response.status, responseBody);
  }
  if (!response.body) throw new ApiError("Streaming response body is unavailable", response.status, null);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const emit = (line: string) => {
    const trimmed = line.trim();
    if (trimmed) onEvent(JSON.parse(trimmed) as T);
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    lines.forEach(emit);
    if (done) break;
  }
  emit(buffer);
}
