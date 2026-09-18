import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";

class IdleWebSocket {
    onopen: (() => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onclose: (() => void) | null = null;
    close(): void {}
    send(): void {}
}

describe("App", () => {
    afterEach(() => {
        vi.restoreAllMocks();
        vi.unstubAllGlobals();
    });

    it("renders the bootstrap shell", () => {
        // Keep network and sockets idle: a real jsdom socket closes asynchronously and could
        // schedule a React update after the test environment is torn down.
        vi.spyOn(globalThis, "fetch").mockReturnValue(new Promise<Response>(() => undefined));
        vi.stubGlobal("WebSocket", IdleWebSocket);
        render(<App />);
        expect(screen.getByRole("heading", { name: "ToneWatch" })).toBeInTheDocument();
    });
});
