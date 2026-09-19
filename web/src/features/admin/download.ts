import { apiUrl } from "../../lib/urls";
import { csrfToken, errorText } from "./shared";

export async function download(path: string, init?: RequestInit): Promise<void> {
    const headers = new Headers(init?.headers);
    if (init?.method && init.method !== "GET") {
        const csrf = csrfToken();
        if (csrf) headers.set("X-CSRF-Token", csrf);
    }
    const response = await fetch(apiUrl(path), { ...init, headers, credentials: "same-origin" });
    if (!response.ok) {
        const body = await response.json().catch(() => undefined);
        throw Object.assign(new Error(`Request failed (${response.status})`), {
            status: response.status,
            body,
        });
    }
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download =
        response.headers.get("Content-Disposition")?.match(/filename="?([^";]+)|$/)?.[1] ||
        "download";
    anchor.click();
    URL.revokeObjectURL(href);
}

export { errorText };
