import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AdminAlerts } from "../src/features/admin/AdminAlerts";
import { Deliveries } from "../src/features/admin/Deliveries";
import { Health } from "../src/features/admin/Health";
import {
    formatBytes,
    formatDuration,
    formatFactor,
    formatForecast,
} from "../src/features/admin/shared";

const response = (value: unknown, status = 200, headers?: Record<string, string>) => {
    const init: ResponseInit = { status };
    if (headers) init.headers = headers;
    return Promise.resolve(new Response(JSON.stringify(value), init));
};

afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    history.pushState({}, "", "/");
});

describe("M19c health", () => {
    const fixture = {
        sources: [
            {
                id: "fixture",
                name: "Fixture source",
                type: "file",
                realtime_factor: 1.2,
                dropped_frames: 2,
                late_frames: 3,
                restarts: 1,
                last_error: null,
                last_restart_at: null,
                feed_health_history: [{ healthy: true, reason: null, at: "2026-01-01T00:00:00Z" }],
                level: null,
                squelch_open: null,
            },
            {
                id: "silent",
                name: "Silent source",
                type: "file",
                realtime_factor: null,
                dropped_frames: null,
                late_frames: null,
                restarts: null,
                last_restart_at: null,
                last_error: null,
                feed_health_history: [],
                level: null,
                squelch_open: null,
            },
        ],
        service: {
            subscribers: [
                { id: "0", depth: 4, dropped: 1, lag_s: 20.25 },
                { id: "1", depth: 0, dropped: 0, lag_s: null },
            ],
        },
        storage: {
            recordings_bytes: 10,
            free_bytes: 20,
            total_bytes: 100,
            used_bytes: 80,
            db_bytes: 30,
            retention_forecast: { days_until_full: null },
        },
        outputs: [
            {
                id: "target",
                name: "Target",
                last_success_at: null,
                last_error_at: null,
                last_error: null,
                consecutive_failures: 0,
                type: "mqtt",
                connection: false,
            },
            {
                id: "script",
                name: "Script",
                type: "script",
                last_success_at: null,
                last_error_at: null,
                last_error: null,
                consecutive_failures: 0,
                connection: null,
            },
        ],
        cad_feeds: [
            {
                id: "cad",
                name: "CAD",
                connected: true,
                availability: "ok",
                last_message_at: null,
                invalid_total: 0,
                active_incidents: 2,
            },
        ],
        build: { version: "1", build: null, uptime_s: 4 },
    };
    it("renders all sections, nulls as em dash, and warns below 1.5x", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(response(fixture));
        render(<Health />);
        expect(await screen.findByText("Fixture source")).toBeInTheDocument();
        expect(screen.getByText("Sources")).toBeInTheDocument();
        expect(screen.getByText("Event bus")).toBeInTheDocument();
        expect(screen.getByText("Storage")).toBeInTheDocument();
        expect(screen.getByText("Outputs")).toBeInTheDocument();
        expect(screen.getByText("CAD feeds")).toBeInTheDocument();
        expect(screen.getByRole("heading", { name: "Build" })).toBeInTheDocument();
        expect(screen.getByText(/below 1.5/)).toBeInTheDocument();
        expect(screen.getByText("no growth")).toBeInTheDocument();
        expect(screen.getByText("MQTT disconnected")).toBeInTheDocument();
        expect(screen.getByLabelText("1 healthy, 0 unhealthy")).toBeInTheDocument();
        expect(screen.getByLabelText("no history")).toBeInTheDocument();
    });
    it("formats health values for people", () => {
        expect(formatFactor(null)).toBe("—");
        expect(formatFactor(2960.6)).toBe(">1000×");
        expect(formatFactor(1.26)).toBe("1.3×");
        expect(formatBytes(null)).toBe("—");
        expect(formatBytes(0)).toBe("0 B");
        expect(formatBytes(22220)).toBe("21.7 KB");
        expect(formatBytes(2222222)).toBe("2.1 MB");
        expect(formatBytes(131318185075)).toBe("122.3 GB");
        expect(formatBytes(1099511627776)).toBe("1.0 TB");
        expect(formatDuration(null)).toBe("—");
        expect(formatDuration(3)).toBe("00m 03s");
        expect(formatDuration(3723)).toBe("1h 02m 03s");
        expect(formatForecast(null)).toBe("no growth");
        expect(formatForecast(1493.4)).toBe("1,493 days");
    });
    it("pauses polling while the document is hidden", async () => {
        vi.useFakeTimers();
        const fetchMock = vi.spyOn(globalThis, "fetch").mockReturnValue(response(fixture));
        render(<Health />);
        await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
        Object.defineProperty(document, "hidden", { configurable: true, value: true });
        await vi.advanceTimersByTimeAsync(20000);
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });
});

describe("M19c admin alerts", () => {
    const config = {
        alert_targets: [{ id: "one", name: "One" }],
        admin_alerts: {
            enabled: false,
            targets: [],
            feed_unhealthy_min: 5,
            disk_used_pct: 90,
            disk_forecast_days: 7,
            target_failures: 5,
            realtime_factor_min: 1.5,
            realtime_factor_min_s: 300,
            min_interval_s: 300,
            max_per_hour: 6,
        },
        secret: "[REDACTED]",
    };
    it("saves the complete body with If-Match and renders readable 422 bounds", async () => {
        const calls: RequestInit[] = [];
        vi.spyOn(globalThis, "fetch").mockImplementation((_, init) => {
            if (init?.method === "PUT") calls.push(init);
            return init?.method === "PUT"
                ? response({ detail: [{ msg: "greater than or equal to 1" }] }, 422)
                : response(config, 200, { ETag: "v1" });
        });
        render(<AdminAlerts />);
        await screen.findByLabelText("Enable admin alerts");
        fireEvent.click(screen.getByLabelText("Enable admin alerts"));
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        expect(await screen.findByText(/greater than or equal to 1/)).toBeInTheDocument();
        expect(new Headers(calls[0]?.headers).get("If-Match")).toBe("v1");
        expect(String(calls[0]?.body)).toContain('"secret":"[REDACTED]"');
    });
    it("shows the conflict message on 412", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((_, init) =>
            init?.method === "PUT" ? response({}, 412) : response(config, 200, { ETag: "v1" }),
        );
        render(<AdminAlerts />);
        await screen.findByLabelText("Enable admin alerts");
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        expect(await screen.findByText(/changed elsewhere, reload/)).toBeInTheDocument();
    });
});

describe("M19c deliveries", () => {
    const item = (id: number, ok: boolean) => ({
        id,
        call_id: "call-1",
        target_id: "target",
        phase: "pre_alert",
        attempt_no: 1,
        ok,
        status_code: ok ? 200 : 500,
        error: ok ? null : "<b>offline</b>",
        created_at: "2026-01-01T00:00:00Z",
        retry: false,
    });
    it("serializes filters, appends cursor pages without duplicates, and only retries failures as text", async () => {
        const urls: string[] = [];
        vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
            urls.push(String(input));
            if (init?.method === "POST") return response({ ok: true });
            return response(
                urls.length === 1
                    ? { items: [item(1, true), item(2, false)], next_cursor: "next" }
                    : { items: [item(2, false), item(3, false)], next_cursor: null },
            );
        });
        history.pushState({}, "", "/admin/deliveries");
        render(<Deliveries />);
        await screen.findByText("<b>offline</b>");
        expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: "Retry succeeded" })).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Load more" }));
        await waitFor(() => expect(screen.getAllByText("<b>offline</b>")).toHaveLength(2));
        expect(screen.getAllByRole("row")).toHaveLength(4);
        expect(urls.some((url) => url.includes("cursor=next"))).toBe(true);
        window.confirm = vi.fn(() => true);
        fireEvent.click(screen.getAllByRole("button", { name: "Retry" })[0]!);
        expect(await screen.findByText(/Retry succeeded/)).toBeInTheDocument();
    });

    it.each([
        [409, { detail: "attempt already succeeded" }, "Already succeeded"],
        [409, { detail: "call unavailable" }, "Call or target no longer exists"],
        [429, { detail: "retry_in_flight" }, "A retry is already running"],
        [200, { ok: false, error: "rate_limited" }, "Rate limited"],
    ])("renders retry result %s", async (status, body, expected) => {
        vi.spyOn(globalThis, "fetch").mockImplementation((_, init) =>
            init?.method === "POST"
                ? response(body, status)
                : response({ items: [item(9, false)], next_cursor: null }),
        );
        window.confirm = vi.fn(() => true);
        render(<Deliveries />);
        fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
        expect(await screen.findByText(expected)).toBeInTheDocument();
    });

    it("keeps filter state in the URL", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(response({ items: [], next_cursor: null }));
        render(<Deliveries />);
        fireEvent.change(await screen.findByLabelText("Phase"), { target: { value: "closed" } });
        await waitFor(() => expect(window.location.search).toContain("phase=closed"));
    });
});
