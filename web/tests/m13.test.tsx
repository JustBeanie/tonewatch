import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";
import { relativeTime } from "../src/features/discovered/DiscoveredTones";

class Socket {
    static OPEN = 1;
    readyState = 1;
    onopen = () => {};
    onclose = () => {};
    onmessage = () => {};
    send() {}
    close() {
        this.onclose();
    }
}

const item = {
    id: 7,
    frequencies: [1000, 1500],
    durations: [1, 2],
    count: 3,
    last_seen: "2026-09-12T12:00:00Z",
    source_ids: ["radio"],
    status: "new",
    best_clip_recording_path: "recordings/discovered/7.mp3",
};

function json(value: unknown) {
    return Promise.resolve(new Response(JSON.stringify(value), { status: 200 }));
}

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    history.pushState({}, "", "/");
});

describe("discovered tones", () => {
    it("formats relative times in both directions", () => {
        const now = Date.now();
        expect(relativeTime(new Date(now - 30_000).toISOString())).toBe("30s ago");
        expect(relativeTime(new Date(now + 30_000).toISOString())).toBe("in 30s");
        expect(relativeTime(new Date(now - 5 * 60_000).toISOString())).toBe("5m ago");
        expect(relativeTime(new Date(now + 5 * 60_000).toISOString())).toBe("in 5m");
        expect(relativeTime(new Date(now - 2 * 60 * 60_000).toISOString())).toBe("2h ago");
        expect(relativeTime(new Date(now + 2 * 60 * 60_000).toISOString())).toBe("in 2h");
        expect(relativeTime(new Date(now - 2 * 86_400_000).toISOString())).toBe("2d ago");
        expect(relativeTime(new Date(now + 2 * 86_400_000).toISOString())).toBe("in 2d");
    });

    it("renders filters and an evidence player", async () => {
        vi.stubGlobal("WebSocket", Socket);
        vi.spyOn(globalThis, "fetch").mockReturnValue(json({ items: [item] }));
        history.pushState({}, "", "/discovered-tones");
        render(<App />);
        expect(await screen.findByText("1000.0 / 1500.0")).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("Status"), { target: { value: "dismissed" } });
        fireEvent.change(screen.getByLabelText("Source"), { target: { value: "radio" } });
        expect(screen.getByRole("columnheader", { name: "Times heard" })).toBeInTheDocument();
    });

    it("confirms dismiss before changing the cluster", async () => {
        vi.stubGlobal("WebSocket", Socket);
        const fetch = vi.spyOn(globalThis, "fetch").mockReturnValue(json({ items: [item] }));
        vi.spyOn(window, "confirm").mockReturnValue(false);
        history.pushState({}, "", "/discovered-tones");
        render(<App />);
        fireEvent.click(await screen.findByRole("button", { name: "Dismiss" }));
        expect(fetch).toHaveBeenCalledTimes(1);
    });

    it("promotes into a prefilled tone-set form and carries the cluster id", async () => {
        vi.stubGlobal("WebSocket", Socket);
        const draft = {
            id: "discovered-1000-1500",
            name: "Discovered 1000/1500 Hz",
            sequence: [
                { freq_hz: 1000, tol_pct: 1.5, min_s: 0.8 },
                { freq_hz: 1500, tol_pct: 1.5, min_s: 1.6 },
            ],
        };
        const fetch = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
            if (String(input).includes("promote")) return json(draft);
            if (init?.method === "POST" && String(input).includes("tonesets")) return json({});
            if (String(input).includes("tonesets")) return json([]);
            return json({ items: [item] });
        });
        history.pushState({}, "", "/discovered-tones");
        render(<App />);
        fireEvent.click(await screen.findByRole("button", { name: "Create tone set" }));
        expect(await screen.findByDisplayValue("Discovered 1000/1500 Hz")).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() =>
            expect(
                String(
                    fetch.mock.calls.find(
                        (call) =>
                            call[1]?.method === "POST" && String(call[0]).endsWith("/tonesets"),
                    )?.[1]?.body,
                ),
            ).toContain('"discovered_tone_id":7'),
        );
    });
});
