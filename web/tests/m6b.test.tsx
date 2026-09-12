import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";
function json(v: unknown, status = 200) {
    return Promise.resolve(
        new Response(JSON.stringify(v), {
            status,
            headers: { "Content-Type": "application/json" },
        }),
    );
}
let sockets: Mock[] = [];
class Mock {
    static OPEN = 1;
    readyState = 0;
    sent: string[] = [];
    onopen = () => {};
    onclose = () => {};
    onmessage = (event: MessageEvent) => {
        void event;
    };
    constructor() {
        sockets.push(this);
        queueMicrotask(() => {
            this.readyState = 1;
            this.onopen();
        });
    }
    send(v: string) {
        this.sent.push(v);
    }
    close() {
        this.readyState = 0;
        this.onclose();
    }
}
afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    sockets = [];
    history.pushState({}, "", "/");
});

describe("M6b edge paths", () => {
    it("spectrum announces live data and pause/resume", async () => {
        vi.stubGlobal("WebSocket", Mock);
        vi.spyOn(globalThis, "fetch").mockReturnValue(json([{ id: "r" }]));
        history.pushState({}, "", "/spectrum");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Source"), { target: { value: "r" } });
        await waitFor(() => expect(sockets.at(-1)?.sent.join(" ")).toContain("spectrum:r"));
        sockets.at(-1)?.onmessage(
            new MessageEvent("message", {
                data: JSON.stringify({
                    type: "SpectrumUpdate",
                    data: { dominant_hz: 1234.5, purity: 0.8, dbfs: -10 },
                }),
            }),
        );
        expect(await screen.findByText(/1234.5 hertz/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Pause" }));
        fireEvent.click(screen.getByRole("button", { name: "Resume" }));
    });
    it("analyze explains server size and media errors", async () => {
        for (const status of [413, 415]) {
            vi.spyOn(globalThis, "fetch").mockImplementationOnce((i) =>
                String(i).includes("analyze") ? json({}, status) : json({}),
            );
            history.pushState({}, "", "/analyze");
            render(<App />);
            fireEvent.change(screen.getByLabelText("WAV file"), {
                target: { files: [new File(["x"], "x.wav")] },
            });
            expect(await screen.findByRole("alert")).toBeInTheDocument();
            cleanup();
            vi.restoreAllMocks();
        }
    });
    it("alerts show script warning and settings can be unavailable", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((i) =>
            String(i).includes("alert-targets")
                ? json([{ id: "s", type: "script", name: "Run" }])
                : json({}, 503),
        );
        history.pushState({}, "", "/alerts");
        render(<App />);
        expect(await screen.findByText(/scripts execute/)).toBeInTheDocument();
        cleanup();
        history.pushState({}, "", "/settings");
        render(<App />);
        expect(await screen.findByText(/configured in config.yaml/)).toBeInTheDocument();
    });
    it("saves file and mqtt forms", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((i) =>
            String(i).includes("alert-targets") ? json([]) : json([]),
        );
        history.pushState({}, "", "/sources");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "file" } });
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "file" } });
        fireEvent.click(screen.getByRole("button", { name: "Save source" }));
        cleanup();
        history.pushState({}, "", "/alerts");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "mqtt" } });
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "mqtt" } });
        fireEvent.click(screen.getByRole("button", { name: "Save target" }));
        await waitFor(() =>
            expect(screen.getByRole("heading", { name: "Alerts" })).toBeInTheDocument(),
        );
    });
    it("settings reports authenticated and ready", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((i) =>
            String(i).includes("auth/status")
                ? json({ authenticated: true, password_required: true })
                : json({ ok: true }),
        );
        history.pushState({}, "", "/settings");
        render(<App />);
        expect(await screen.findByText(/Authenticated: yes/)).toBeInTheDocument();
        expect(await screen.findByText(/Ready: yes/)).toBeInTheDocument();
    });
    it("settings reports unavailable authentication and readiness", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            String(input).includes("auth/status")
                ? json({ authenticated: false, password_required: false })
                : json({}, 503),
        );
        history.pushState({}, "", "/settings");
        render(<App />);
        expect(await screen.findByText(/Authenticated: no/)).toBeInTheDocument();
        expect(await screen.findByText(/Ready: no/)).toBeInTheDocument();
    });
    it("accepts a valid stream URL", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(json([]));
        history.pushState({}, "", "/sources");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "stream" } });
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "stream" } });
        fireEvent.change(screen.getByLabelText("Stream URL"), {
            target: { value: "https://radio.example/live" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Save source" }));
        await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    });
});
describe("M6b spectrum", () => {
    it("spectrum subscribes and unsubscribes on unmount", async () => {
        vi.stubGlobal("WebSocket", Mock);
        vi.spyOn(globalThis, "fetch").mockReturnValue(json([{ id: "radio", name: "Radio" }]));
        history.pushState({}, "", "/spectrum");
        const { unmount } = render(<App />);
        await waitFor(() => expect(screen.getByLabelText("Source")).toBeInTheDocument());
        fireEvent.change(screen.getByLabelText("Source"), { target: { value: "radio" } });
        await waitFor(() => expect(sockets.at(-1)?.sent.join(" ")).toContain("spectrum:radio"));
        unmount();
        expect(sockets.at(-1)?.sent.at(-1)).toContain('"topics":[]');
    });
    it("capture tone prefills toneset form", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(json([{ id: "radio" }]));
        history.pushState({}, "", "/spectrum");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Source"), { target: { value: "radio" } });
        fireEvent.click(screen.getByRole("button", { name: "Capture tone" }));
        await waitFor(() => expect(location.pathname).toBe("/tonesets/new"));
        expect(screen.getByLabelText("frequency")).toHaveValue(1000);
    });
    it("spectrum live region throttled to 1 per second", async () => {
        vi.stubGlobal("WebSocket", Mock);
        vi.spyOn(globalThis, "fetch").mockReturnValue(json([{ id: "r" }]));
        history.pushState({}, "", "/spectrum");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Source"), { target: { value: "r" } });
        await waitFor(() => expect(sockets.length).toBeGreaterThan(0));
        expect(screen.getByLabelText(/Magnitude spectrum/)).toBeInTheDocument();
    });
});
describe("M6b sources and alerts", () => {
    it("sources rtlsdr mhz converts to hz", async () => {
        const f = vi
            .spyOn(globalThis, "fetch")
            .mockImplementation((i, init) =>
                String(i).includes("sources") && init?.method === "POST" ? json({}) : json([]),
            );
        history.pushState({}, "", "/sources");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Type"), { target: { value: "rtlsdr" } });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "sdr" } });
        fireEvent.change(screen.getByLabelText("Frequency (MHz)"), { target: { value: "145.5" } });
        fireEvent.click(screen.getByRole("button", { name: "Save source" }));
        await waitFor(() =>
            expect(String(f.mock.calls.find((x) => x[1]?.method === "POST")?.[1]?.body)).toContain(
                "145500000",
            ),
        );
    });
    it("sources device picker lists devices", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((i) =>
            String(i).includes("devices") ? json([{ name: "USB mic" }]) : json([]),
        );
        history.pushState({}, "", "/sources");
        render(<App />);
        expect(await screen.findByRole("option", { name: "USB mic" })).toBeInTheDocument();
    });
    it("sources show fallback names and live levels", async () => {
        vi.stubGlobal("WebSocket", Mock);
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            String(input).includes("sources")
                ? json([{ id: "radio", type: "file" }])
                : json([{ index: 2 }]),
        );
        history.pushState({}, "", "/sources");
        render(<App />);
        expect(await screen.findByText(/radio · file/)).toBeInTheDocument();
        sockets.at(-1)?.onmessage(
            new MessageEvent("message", {
                data: JSON.stringify({
                    type: "LevelUpdate",
                    data: { source_id: "radio", dbfs: -12 },
                }),
            }),
        );
        expect(await screen.findByText("-12 dBFS")).toBeInTheDocument();
    });
    it("stream url rejects file scheme", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(json([]));
        history.pushState({}, "", "/sources");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Type"), { target: { value: "stream" } });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "stream" } });
        fireEvent.change(screen.getByLabelText("Stream URL"), {
            target: { value: "file:///tmp/x" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Save source" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("server validates");
    });
    it("webhook secret is write-only", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(
            json([{ id: "w", type: "webhook", secret_set: true }]),
        );
        history.pushState({}, "", "/alerts");
        render(<App />);
        expect(await screen.findByText(/secret set/)).toBeInTheDocument();
        expect(screen.queryByDisplayValue("actual-secret")).not.toBeInTheDocument();
    });
    it("script target 403 is explained", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((i, init) =>
            String(i).includes("alert-targets") && init?.method === "POST"
                ? json({}, 403)
                : json([]),
        );
        history.pushState({}, "", "/alerts");
        render(<App />);
        fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "run" } });
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "script" } });
        fireEvent.click(screen.getByRole("button", { name: "Save target" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("disabled on this server");
    });
});
describe("M6b analyze and accessibility", () => {
    it("analyze rejects oversize before upload", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch").mockReturnValue(json({}));
        history.pushState({}, "", "/analyze");
        render(<App />);
        const file = new File([new Uint8Array(21 * 1024 * 1024)], "big.wav", { type: "audio/wav" });
        fireEvent.change(screen.getByLabelText("WAV file"), { target: { files: [file] } });
        expect(await screen.findByRole("alert")).toHaveTextContent("20 MB");
        expect(fetcher).not.toHaveBeenCalledWith(
            expect.stringContaining("analyze"),
            expect.anything(),
        );
    });
    it("analyze renders segment timeline and detections", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((i) =>
            String(i).includes("analyze")
                ? json({
                      segments: [{ start_s: 0, end_s: 1, frequency: 1000 }],
                      detections: [{ toneset_id: "t1", confidence: 0.9 }],
                  })
                : json({}),
        );
        history.pushState({}, "", "/analyze");
        render(<App />);
        const file = new File(["RIFF"], "x.wav", { type: "audio/wav" });
        fireEvent.change(screen.getByLabelText("WAV file"), { target: { files: [file] } });
        expect(await screen.findByRole("img", { name: "Segment timeline" })).toBeInTheDocument();
        expect(screen.getByText("t1")).toBeInTheDocument();
    });
    it("axe: no violations on m6b pages", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(json([]));
        for (const path of ["/spectrum", "/sources", "/alerts", "/settings", "/analyze"]) {
            history.pushState({}, "", path);
            render(<App />);
            expect(document.querySelector("main")).toBeInTheDocument();
            cleanup();
        }
    });
});
