import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";
import { request } from "../src/api/client";
import { appUrl, websocketUrl } from "../src/lib/urls";
import { ToneWatchSocket } from "../src/lib/ws";

const calls = [
    { id: "c1", started_at: "2026-01-01T00:00:00Z", source_id: "radio", status: "closed" },
];
const toneSet = {
    id: "t1",
    name: "Fire",
    enabled: true,
    sequence: [{ frequency: 1000, tolerance_pct: 1, min_s: 1, max_s: 2 }],
};
let sockets: MockSocket[] = [];
class MockSocket {
    static OPEN = 1;
    readyState = 0;
    sent: string[] = [];
    onopen = () => {};
    onclose = () => {};
    onmessage: (event: MessageEvent) => void = () => {};
    constructor() {
        sockets.push(this);
        queueMicrotask(() => {
            this.readyState = 1;
            this.onopen();
        });
    }
    send(value: string) {
        if (this.readyState !== 1)
            throw new DOMException("Sent before connected", "InvalidStateError");
        this.sent.push(value);
    }
    close() {
        this.readyState = 0;
        this.onclose();
    }
    emit(message: unknown) {
        this.onmessage(new MessageEvent("message", { data: JSON.stringify(message) }));
    }
}
function json(value: unknown, status = 200) {
    return Promise.resolve(
        new Response(JSON.stringify(value), {
            status,
            headers: { "Content-Type": "application/json" },
        }),
    );
}
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sockets = [];
    history.pushState({}, "", "/");
});

describe("M6a shared clients", () => {
    it("urls respect ingress base path", () => {
        const original = document.baseURI;
        const base = document.createElement("base");
        base.href = "https://host/ingress/token/";
        document.head.append(base);
        expect(appUrl("api/calls")).toBe("https://host/ingress/token/api/calls");
        expect(websocketUrl()).toBe("wss://host/ingress/token/api/ws");
        base.remove();
        expect(document.baseURI).toBe(original);
    });
    it("client sends csrf header on mutations", async () => {
        Object.defineProperty(document, "cookie", {
            configurable: true,
            value: "tonewatch_csrf=abc",
        });
        const fetcher = vi.spyOn(globalThis, "fetch").mockReturnValue(json({ ok: true }));
        await request("tonesets", { method: "POST", body: "{}" });
        expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ credentials: "same-origin" });
        expect(new Headers(fetcher.mock.calls[0]?.[1]?.headers).get("X-CSRF-Token")).toBe("abc");
    });
    it("401 redirects to login", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(json({}, 401));
        await expect(request("calls")).rejects.toThrow("Unauthorized");
        expect(location.pathname).toContain("login");
    });
    it("ws reconnects and resubscribes", async () => {
        vi.stubGlobal("WebSocket", MockSocket);
        vi.useFakeTimers();
        const socket = new ToneWatchSocket();
        socket.connect();
        socket.subscribe("events");
        await vi.runAllTicks();
        expect(sockets[0]?.sent[0]).toContain("events");
        sockets[0]?.close();
        vi.advanceTimersByTime(1000);
        await vi.runAllTicks();
        expect(sockets[1]?.sent[0]).toContain("events");
        vi.useRealTimers();
        socket.close();
    });
});

describe("M6a pages", () => {
    it("login accepts a password and theme toggle persists", async () => {
        const fetcher = vi
            .spyOn(globalThis, "fetch")
            .mockImplementation((input) =>
                String(input).includes("auth/status")
                    ? json({ authenticated: false, password_required: true })
                    : json({ ok: true }),
            );
        history.pushState({}, "", "/login");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Password"), { target: { value: "secret" } });
        fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
        await waitFor(() =>
            expect(fetcher).toHaveBeenCalledWith(
                expect.stringContaining("auth/login"),
                expect.objectContaining({ method: "POST" }),
            ),
        );
    });
    it("login bypasses password when none is configured", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(
            json({ authenticated: false, password_required: false }),
        );
        history.pushState({}, "", "/login");
        render(<App />);
        await waitFor(() => expect(location.pathname).toBe("/"));
    });
    it("theme toggle and audio format switch are available", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            String(input).includes("calls/c1")
                ? json({
                      ...calls[0],
                      tone_sets: [],
                      recordings: [
                          { id: 1, format: "mp3", url: "/a.mp3" },
                          { id: 2, format: "opus", url: "/a.opus" },
                      ],
                      alert_attempts: [],
                  })
                : json({ items: [] }),
        );
        render(<App />);
        fireEvent.click(screen.getByRole("button", { name: "Dark theme" }));
        expect(document.documentElement.dataset.theme).toBe("dark");
        history.pushState({}, "", "/calls/c1");
        fireEvent.popState(window);
        await waitFor(() => expect(screen.getByLabelText("Format")).toBeInTheDocument());
        fireEvent.change(screen.getByLabelText("Format"), { target: { value: "opus" } });
        expect(document.querySelector("audio")).toHaveAttribute("src", "/a.opus");
    });
    it("dashboard shows live call from ws event", async () => {
        vi.stubGlobal("WebSocket", MockSocket);
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            String(input).includes("calls") ? json({ items: [] }) : json({}),
        );
        render(<App />);
        await waitFor(() => expect(sockets.length).toBeGreaterThan(0));
        sockets[0]?.emit({
            type: "ToneDetected",
            data: { call_id: "live", source_id: "radio", status: "detected", started_at: "now" },
        });
        await waitFor(() => expect(screen.getByText(/radio · detected/)).toBeInTheDocument());
    });
    it("dashboard shows feed health reason and level payload", async () => {
        vi.stubGlobal("WebSocket", MockSocket);
        vi.spyOn(globalThis, "fetch").mockReturnValue(json({ items: [] }));
        render(<App />);
        await waitFor(() => expect(sockets.length).toBeGreaterThanOrEqual(2));
        sockets[0]?.emit({ type: "FeedHealthChanged", data: { reason: "No frames" } });
        sockets[1]?.emit({ type: "ChannelLevel", data: { dbfs: -12.5 } });
        expect(await screen.findByText(/No frames/)).toBeInTheDocument();
        expect(await screen.findByText("-12.5 dBFS")).toBeInTheDocument();
    });
    it("level meter is accessible", async () => {
        vi.stubGlobal("WebSocket", MockSocket);
        vi.spyOn(globalThis, "fetch").mockReturnValue(json({ items: [] }));
        render(<App />);
        expect((await screen.findAllByRole("meter"))[0]).toHaveAttribute("aria-valuenow", "-100");
    });
    it("calls filters sync to url", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(json({ items: calls }));
        history.pushState({}, "", "/calls");
        render(<App />);
        fireEvent.change(screen.getByLabelText("Source"), { target: { value: "radio" } });
        fireEvent.click(screen.getByRole("button", { name: "Filter" }));
        await waitFor(() => expect(location.search).toContain("source=radio"));
    });
    it("call detail plays api-provided recording url", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(
            json({
                ...calls[0],
                tone_sets: [],
                recordings: [{ id: 1, format: "mp3", url: "/ingress/x/api/recordings/1" }],
                alert_attempts: [],
            }),
        );
        history.pushState({}, "", "/calls/c1");
        render(<App />);
        await waitFor(() =>
            expect(document.querySelector("audio")).toHaveAttribute(
                "src",
                "/ingress/x/api/recordings/1",
            ),
        );
    });
    it("toneset form validates ranges", async () => {
        render(<App />);
        fireEvent.click(screen.getAllByRole("link", { name: "Tone sets" })[0]!);
        fireEvent.click(await screen.findByRole("link", { name: "New tone set" }));
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Test" } });
        fireEvent.change(screen.getByLabelText("frequency"), { target: { value: "100" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("Check frequency");
    });
    it("toneset 422 maps to fields", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) =>
            String(input).includes("tonesets") && init?.method === "POST"
                ? json(
                      {
                          detail: [{ loc: ["body", "sequence", 0, "frequency"], msg: "too low" }],
                      },
                      422,
                  )
                : json([]),
        );
        render(<App />);
        fireEvent.click(screen.getAllByRole("link", { name: "Tone sets" })[0]!);
        fireEvent.click(await screen.findByRole("link", { name: "New tone set" }));
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Test" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("body.sequence.0.frequency");
        expect(fetcher).toHaveBeenCalled();
    });
    it("toneset delete 409 shows referrers", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((input, init) =>
            init?.method === "DELETE"
                ? json({ detail: { referrers: ["source-1"] } }, 409)
                : json([toneSet]),
        );
        vi.spyOn(window, "confirm").mockReturnValue(true);
        const alert = vi.spyOn(window, "alert").mockImplementation(() => {});
        render(<App />);
        fireEvent.click(screen.getByRole("link", { name: "Tone sets" }));
        await waitFor(() => expect(screen.getByText("Fire")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Delete" }));
        await waitFor(() =>
            expect(alert).toHaveBeenCalledWith(expect.stringContaining("source-1")),
        );
    });
    it("toneset test button triggers test endpoint", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(() => json([toneSet]));
        render(<App />);
        fireEvent.click(screen.getAllByRole("link", { name: "Tone sets" })[0]!);
        await waitFor(() => expect(screen.getByText("Fire")).toBeInTheDocument());
        fireEvent.click(screen.getByRole("button", { name: "Test" }));
        await waitFor(() =>
            expect(fetcher).toHaveBeenCalledWith(
                expect.stringContaining("tonesets/t1/test"),
                expect.objectContaining({ method: "POST" }),
            ),
        );
    });
    it("valid tone set saves and websocket delivers messages", async () => {
        vi.stubGlobal("WebSocket", MockSocket);
        const fetcher = vi
            .spyOn(globalThis, "fetch")
            .mockImplementation((input) =>
                String(input).includes("tonesets") ? json([]) : json({ items: [] }),
            );
        render(<App />);
        fireEvent.click(screen.getAllByRole("link", { name: "Tone sets" })[0]!);
        fireEvent.click(await screen.findByRole("link", { name: "New tone set" }));
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() =>
            expect(fetcher).toHaveBeenCalledWith(
                expect.stringContaining("/api/tonesets"),
                expect.objectContaining({ method: "POST" }),
            ),
        );
        const socket = new ToneWatchSocket();
        const listener = vi.fn();
        socket.onMessage(listener);
        socket.connect();
        socket.subscribe("events");
        await vi.waitFor(() => expect(sockets.length).toBeGreaterThan(0));
        sockets.at(-1)?.emit({ type: "pong", data: {} });
        expect(listener).toHaveBeenCalled();
        socket.unsubscribe("events");
        socket.close();
    });
    it("axe: no violations on key pages", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(json({ items: [] }));
        render(<App />);
        expect(document.querySelector("main")).toBeInTheDocument();
    });
});
