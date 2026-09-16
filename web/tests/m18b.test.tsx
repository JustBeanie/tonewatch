import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";

function json(value: unknown, status = 200) {
    return Promise.resolve(
        new Response(JSON.stringify(value), {
            status,
            headers: { "Content-Type": "application/json" },
        }),
    );
}

function alertsPage(
    fetchImpl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
) {
    vi.spyOn(globalThis, "fetch").mockImplementation(fetchImpl);
    history.pushState({}, "", "/alerts");
    render(<App />);
}

afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
});

describe("M18b Meshtastic alert UI", () => {
    it("selecting meshtastic renders the broker, mesh, and safety fields", async () => {
        alertsPage((input) => (String(input).includes("alert-targets") ? json([]) : json({})));
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "meshtastic" } });
        expect(screen.getByLabelText("Broker host")).toBeInTheDocument();
        expect(screen.getByLabelText("Gateway node ID")).toBeInTheDocument();
        expect(screen.getByLabelText("Channel index")).toBeInTheDocument();
        expect(screen.getByText(/URLs never go on the mesh/)).toBeInTheDocument();
    });

    it("typing a template makes one debounced authoritative preview call", async () => {
        vi.useFakeTimers();
        const previewCalls: string[] = [];
        alertsPage((input, init) => {
            if (String(input).includes("meshtastic/preview")) {
                previewCalls.push(String(init?.body));
                return json({ text: "TEST AFD", bytes: 9, max_bytes: 200, truncated: false });
            }
            return json([]);
        });
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "meshtastic" } });
        fireEvent.change(screen.getByLabelText("Template"), {
            target: { value: "{agency_short}" },
        });
        vi.advanceTimersByTime(299);
        expect(previewCalls).toHaveLength(0);
        await vi.advanceTimersByTimeAsync(1);
        expect(previewCalls).toHaveLength(1);
        expect(screen.getByText("9 / 200 bytes")).toBeInTheDocument();
        vi.useRealTimers();
    });

    it("shows the server truncated warning", async () => {
        vi.useFakeTimers();
        alertsPage((input) =>
            String(input).includes("meshtastic/preview")
                ? json({ text: "TEST…", bytes: 8, max_bytes: 8, truncated: true })
                : json([]),
        );
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "meshtastic" } });
        fireEvent.change(screen.getByLabelText("Template"), { target: { value: "long" } });
        await vi.advanceTimersByTimeAsync(300);
        expect(screen.getByText(/Message truncated/)).toBeInTheDocument();
        vi.useRealTimers();
    });

    it("keeps save disabled on public channel until acknowledged", async () => {
        alertsPage((input) => (String(input).includes("alert-targets") ? json([]) : json({})));
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "meshtastic" } });
        const save = screen.getByRole("button", { name: "Save target" });
        expect(save).toBeDisabled();
        fireEvent.click(screen.getByLabelText(/acknowledge that channel 0/));
        expect(save).toBeEnabled();
    });

    it("sends a test to the selected alert target route", async () => {
        const calls: string[] = [];
        alertsPage((input, init) => {
            calls.push(`${init?.method ?? "GET"} ${String(input)}`);
            return String(input).includes("/test")
                ? json({ ok: true })
                : json([{ id: "mesh", name: "Mesh", type: "meshtastic" }]);
        });
        fireEvent.click(await screen.findByRole("button", { name: "Send test" }));
        await screen.findByText("Test sent");
        expect(
            calls.some((call) => call.includes("POST") && call.includes("alert-targets/mesh/test")),
        ).toBe(true);
        expect(calls.some((call) => call.includes("tonesets/"))).toBe(false);
    });

    it("shows an inline server error for an invalid preview", async () => {
        vi.useFakeTimers();
        alertsPage((input) =>
            String(input).includes("meshtastic/preview")
                ? json({ detail: "invalid target" }, 422)
                : json([]),
        );
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "meshtastic" } });
        fireEvent.change(screen.getByLabelText("Template"), { target: { value: "bad" } });
        await vi.advanceTimersByTimeAsync(300);
        expect(screen.getByText("Preview: invalid target")).toBeInTheDocument();
    });

    it("serializes and saves a Meshtastic target", async () => {
        const posts: string[] = [];
        alertsPage((input, init) => {
            if (init?.method === "POST") posts.push(String(init.body));
            return json([]);
        });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Mesh" } });
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "meshtastic" } });
        fireEvent.change(screen.getByLabelText("Channel index"), { target: { value: "1" } });
        fireEvent.change(screen.getByLabelText("Broker host"), { target: { value: "broker" } });
        fireEvent.change(screen.getByLabelText("Destination"), { target: { value: "broadcast" } });
        fireEvent.change(screen.getByLabelText("Maximum bytes"), { target: { value: "100" } });
        fireEvent.change(screen.getByLabelText("Phases"), {
            target: { value: "pre_alert,closed" },
        });
        fireEvent.change(screen.getByLabelText("Minimum interval seconds"), {
            target: { value: "10" },
        });
        fireEvent.change(screen.getByLabelText("Maximum per hour"), { target: { value: "5" } });
        fireEvent.change(screen.getByLabelText("Timezone"), { target: { value: "UTC" } });
        fireEvent.click(screen.getByRole("button", { name: "Save target" }));
        await waitFor(() => expect(posts).toHaveLength(1));
        expect(JSON.parse(posts[0]!).type).toBe("meshtastic");
    });

    it("shows a failed send-test response", async () => {
        alertsPage((input) =>
            String(input).includes("/test")
                ? json({ ok: false, error: "offline" })
                : json([{ id: "mesh", name: "Mesh", type: "meshtastic" }]),
        );
        fireEvent.click(await screen.findByRole("button", { name: "Send test" }));
        expect(await screen.findByText("offline")).toBeInTheDocument();
    });

    it("keeps webhook and script form behavior available", async () => {
        const posts: string[] = [];
        alertsPage((input, init) => {
            if (init?.method === "POST") posts.push(String(init.body));
            return json([]);
        });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Hook" } });
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "webhook" } });
        fireEvent.change(screen.getByLabelText("URL"), {
            target: { value: "https://example.com" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Save target" }));
        await waitFor(() => expect(posts).toHaveLength(1));
        fireEvent.change(screen.getByLabelText("Type"), { target: { value: "script" } });
        fireEvent.click(screen.getByRole("button", { name: "Save target" }));
        await waitFor(() => expect(posts).toHaveLength(2));
    });

    it("reports a save failure inline", async () => {
        alertsPage((input, init) =>
            init?.method === "POST" ? json({ detail: "bad target" }, 422) : json([]),
        );
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Bad" } });
        fireEvent.click(screen.getByRole("button", { name: "Save target" }));
        expect(await screen.findByText("bad target")).toBeInTheDocument();
    });

    it("reports a failed test request", async () => {
        alertsPage((input) =>
            String(input).includes("/test")
                ? Promise.reject(new Error("network"))
                : json([{ id: "mesh", name: "Mesh", type: "meshtastic" }]),
        );
        fireEvent.click(await screen.findByRole("button", { name: "Send test" }));
        expect(await screen.findByText("Unable to save target")).toBeInTheDocument();
    });

    it("keeps the form usable when the target list is unavailable", async () => {
        alertsPage((input) =>
            String(input).includes("alert-targets")
                ? Promise.reject(new Error("offline"))
                : json({}),
        );
        expect(screen.getByRole("heading", { name: "Alerts" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Save target" })).toBeInTheDocument();
        await Promise.resolve();
    });
});
