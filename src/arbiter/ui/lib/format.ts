export function formatBytes(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = numeric;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size >= 10 || index === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[index]}`;
}

export function formatDate(value: unknown): string {
  if (!value) return "—";
  const date = new Date(String(value));
  return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString();
}

export function shortId(value: unknown): string {
  return value ? String(value).slice(0, 10) : "—";
}

export function asText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

export function classes(...values: Array<string | false | null | undefined>): string {
  return values.filter(Boolean).join(" ");
}

export function statusTone(value: unknown): "good" | "warn" | "bad" | "neutral" {
  const status = String(value ?? "").toLowerCase();
  if (["running", "ready", "healthy", "completed", "approved", "ok", "available", "active"].some((item) => status.includes(item))) return "good";
  if (["pending", "waiting", "created", "paused", "unknown"].some((item) => status.includes(item))) return "warn";
  if (["failed", "error", "stopped", "rejected", "unavailable", "dead", "exited"].some((item) => status.includes(item))) return "bad";
  return "neutral";
}
