export function display(value: unknown): string {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "number" && !Number.isFinite(value)) return "—";
    return String(value);
}

export function formatFactor(value: unknown): string {
    if (
        value === null ||
        value === undefined ||
        typeof value !== "number" ||
        !Number.isFinite(value)
    )
        return "—";
    return value > 1000 ? ">1000×" : `${value.toFixed(1)}×`;
}

export function formatBytes(value: unknown): string {
    if (
        value === null ||
        value === undefined ||
        typeof value !== "number" ||
        !Number.isFinite(value)
    )
        return "—";
    if (value < 1024) return `${Math.round(value)} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let amount = value;
    let unit = "B";
    for (const candidate of units) {
        amount /= 1024;
        unit = candidate;
        if (amount < 1024 || candidate === units.at(-1)) break;
    }
    return `${amount.toFixed(1)} ${unit}`;
}

export function formatDuration(value: unknown): string {
    if (
        value === null ||
        value === undefined ||
        typeof value !== "number" ||
        !Number.isFinite(value)
    )
        return "—";
    const seconds = Math.max(0, Math.floor(value));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const remainder = seconds % 60;
    return `${hours ? `${hours}h ` : ""}${String(minutes).padStart(2, "0")}m ${String(remainder).padStart(2, "0")}s`;
}

export function formatExpiry(value: unknown, now = Date.now()): string {
    if (typeof value !== "string") return "—";
    const expiry = Date.parse(value);
    if (!Number.isFinite(expiry)) return "—";
    const remaining = Math.max(0, expiry / 1000 - now / 1000);
    return `${new Date(expiry).toLocaleString()} (in ${formatDuration(remaining)})`;
}

export function formatForecast(value: unknown): string {
    if (value === null || value === undefined) return "no growth";
    if (typeof value !== "number" || !Number.isFinite(value)) return "—";
    return `${Math.round(value).toLocaleString("en-US")} days`;
}

export function errorText(error: unknown): string {
    const body = (error as { body?: { detail?: unknown } } | null)?.body;
    const detail = body?.detail;
    if (Array.isArray(detail)) return detail.map((item) => String(item?.msg ?? item)).join("; ");
    if (typeof detail === "string") return detail;
    return error instanceof Error ? error.message : "Request failed";
}

export function csrfToken(): string | undefined {
    return document.cookie
        .split("; ")
        .find((part) => part.startsWith("tonewatch_csrf="))
        ?.slice("tonewatch_csrf=".length);
}
