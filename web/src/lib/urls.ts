export function appUrl(path: string): string {
    return new URL(path.replace(/^\//, ""), document.baseURI).toString();
}

export function apiUrl(path: string): string {
    return appUrl(`api/${path.replace(/^\//, "")}`);
}

export function websocketUrl(): string {
    const url = new URL("api/ws", document.baseURI);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
}
