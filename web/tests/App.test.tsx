import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";

class IdleWebSocket {
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onclose: (() => void) | null = null;
    close(): void {}
    send(): void {}
}

describe("App", () => {
    beforeEach(() => {
        // Keep network and sockets idle: a real jsdom socket closes asynchronously and could
        // schedule a React update after the test environment is torn down.
        vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise<Response>(() => undefined));
        vi.stubGlobal("WebSocket", IdleWebSocket);
    });

    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it("renders the bootstrap shell", () => {
        render(<App />);
        expect(screen.getByRole("heading", { name: "ToneWatch" })).toBeInTheDocument();
    });

    it.each([
        ["/map", "Agency map"],
        ["/admin/health", "System health"],
        ["/admin/backup", "Backup"],
    ])("loads %s under an ingress prefix", async (path, heading) => {
        const initialUrl = window.location.href;
        const prefix = "/api/hassio_ingress/fixture";
        const base = document.createElement("base");
        base.href = prefix + "/";
        document.head.append(base);
        window.history.replaceState(null, "", prefix + path);

        const { unmount } = render(<App />);
        try {
            expect(screen.getByRole("navigation", { name: "Main navigation" })).toBeVisible();
            expect(await screen.findByRole("heading", { name: heading })).toBeVisible();
        } finally {
            unmount();
            base.remove();
            window.history.replaceState(null, "", initialUrl);
        }
    });
});
