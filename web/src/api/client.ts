import createClient from "openapi-fetch";
import type { paths } from "./generated/schema";
import { apiUrl, appUrl } from "../lib/urls";

const csrf = (): string | undefined => {
    const item = document.cookie.split("; ").find((part) => part.startsWith("tonewatch_csrf="));
    return item?.slice("tonewatch_csrf=".length);
};

const baseClient = createClient<paths>({ baseUrl: apiUrl(".."), credentials: "same-origin" });

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const method = (init?.method ?? "GET").toUpperCase();
    const headers = new Headers(init?.headers);
    if (method !== "GET" && method !== "HEAD") {
        const token = csrf();
        if (token) headers.set("X-CSRF-Token", token);
    }
    const response = await fetch(apiUrl(path), { ...init, headers, credentials: "same-origin" });
    if (response.status === 401) {
        window.history.pushState({}, "", appUrl("login"));
        window.dispatchEvent(new PopStateEvent("popstate"));
        throw new Error("Unauthorized");
    }
    if (!response.ok) {
        const body: unknown = await response.json().catch(() => undefined);
        throw Object.assign(new Error(`Request failed (${response.status})`), {
            status: response.status,
            body,
        });
    }
    return (await response.json()) as T;
}

export { baseClient };
