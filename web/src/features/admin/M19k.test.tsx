import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { request } from "../../api/client";
import { MemoryRouter } from "react-router";
import { ConfigHistory } from "./ConfigHistory";
import { Drill } from "./Drill";
import { Logs } from "./Logs";
import { download } from "./download";

vi.mock("../../api/client", () => ({ request: vi.fn() }));
vi.mock("../../lib/ws", () => ({ useWsEvents: vi.fn() }));
vi.mock("./download", () => ({ download: vi.fn() }));
const mockedRequest = vi.mocked(request);

beforeEach(() => {
    mockedRequest.mockReset();
    vi.stubGlobal(
        "fetch",
        vi.fn(async () => new Response("{}", { headers: { ETag: '"etag-1"' } })),
    );
});

afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
});

describe("M19k admin UI", () => {
    it("requires drill confirmation, sends the exact body, and links to calls after 202", async () => {
        mockedRequest.mockImplementation(async (path, init) => {
            if (path === "sources") return [{ id: "radio", name: "Radio", enabled: true }];
            if (path === "tonesets") return [{ id: "tones", name: "Tones", enabled: true }];
            if (path === "admin/health") return { sources: [{ id: "radio", realtime_factor: 1 }] };
            if (path === "admin/drill") return { drill_id: "drill-1", expected_duration_s: 12 };
            throw new Error(`unexpected ${path} ${JSON.stringify(init)}`);
        });
        render(
            <MemoryRouter>
                <Drill />
            </MemoryRouter>,
        );
        await waitFor(() =>
            expect(screen.getByRole("option", { name: "Radio" })).toBeInTheDocument(),
        );
        fireEvent.change(screen.getByRole("combobox", { name: "Source" }), {
            target: { value: "radio" },
        });
        fireEvent.change(screen.getByRole("combobox", { name: "Tone set" }), {
            target: { value: "tones" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Start drill" }));
        expect(
            screen.getByText(/real alerts to every configured target.*DRILL/i),
        ).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
        expect(mockedRequest).not.toHaveBeenCalledWith("admin/drill", expect.anything());
        fireEvent.click(screen.getByRole("button", { name: "Start drill" }));
        fireEvent.click(screen.getByRole("button", { name: "Send drill" }));
        await waitFor(() =>
            expect(mockedRequest).toHaveBeenCalledWith(
                "admin/drill",
                expect.objectContaining({
                    body: JSON.stringify({
                        source_id: "radio",
                        toneset_id: "tones",
                        mode: "replace",
                        voice_s: 5,
                        keep: false,
                    }),
                }),
            ),
        );
        expect(await screen.findByRole("link", { name: /calls list/i })).toHaveAttribute(
            "href",
            "/calls",
        );
    });

    it("renders a readable drill rate-limit error", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "sources") return [{ id: "radio", enabled: true }];
            if (path === "tonesets") return [{ id: "tones", enabled: true }];
            if (path === "admin/health") return { sources: [{ id: "radio" }] };
            throw Object.assign(new Error("Request failed"), {
                status: 429,
                body: { detail: "a drill is already active" },
            });
        });
        render(
            <MemoryRouter>
                <Drill />
            </MemoryRouter>,
        );
        await waitFor(() =>
            expect(screen.getByRole("option", { name: "radio" })).toBeInTheDocument(),
        );
        fireEvent.change(screen.getByRole("combobox", { name: "Source" }), {
            target: { value: "radio" },
        });
        fireEvent.change(screen.getByRole("combobox", { name: "Tone set" }), {
            target: { value: "tones" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Start drill" }));
        fireEvent.click(screen.getByRole("button", { name: "Send drill" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("a drill is already active");
    });

    it("rolls back with the current ETag and gates import apply on the same preview", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "admin/config/versions")
                return [
                    {
                        id: "v1",
                        time: "2026-01-01T00:00:00Z",
                        actor: "startup",
                        route: "baseline",
                        sha256: "12345678",
                    },
                ];
            if (path.includes("/diff"))
                return [{ path: "alerts.token", before: "changed", after: "changed" }];
            if (path === "admin/config/import/preview")
                return { diff: [{ path: "sources", before: 1, after: 2 }] };
            return {};
        });
        render(<ConfigHistory />);
        await screen.findByText("startup");
        fireEvent.click(screen.getByText("startup"));
        expect(await screen.findByText(/alerts\.token/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /roll back/i }));
        fireEvent.click(screen.getByRole("button", { name: /confirm rollback/i }));
        await waitFor(() =>
            expect(mockedRequest).toHaveBeenCalledWith(
                "admin/config/versions/v1/rollback",
                expect.objectContaining({ headers: { "If-Match": '"etag-1"' } }),
            ),
        );
        fireEvent.click(screen.getByRole("button", { name: "Include secrets" }));
        fireEvent.change(screen.getByRole("textbox", { name: /secret export confirmation/i }), {
            target: { value: "include-secrets" },
        });
        fireEvent.click(screen.getByRole("button", { name: /download plaintext secrets/i }));
        expect(download).toHaveBeenCalled();
        const content = screen.getByRole("textbox", { name: /configuration content/i });
        const apply = screen.getByRole("button", { name: "Apply" });
        expect(apply).toBeDisabled();
        fireEvent.change(content, { target: { value: "sources: []" } });
        fireEvent.click(screen.getByRole("button", { name: "Preview" }));
        await waitFor(() => expect(apply).toBeEnabled());
        fireEvent.change(content, { target: { value: "sources: [changed]" } });
        expect(apply).toBeDisabled();
    });

    it("polls logs incrementally, renders markup as text, and pauses when hidden", async () => {
        vi.useFakeTimers();
        mockedRequest.mockResolvedValue({
            items: [{ seq: 7, level: "INFO", message: "<script>alert(1)</script>" }],
        });
        render(<Logs />);
        await act(async () => {
            for (let i = 0; i < 5; i += 1) await Promise.resolve();
        });
        expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
        expect(screen.queryByRole("script")).not.toBeInTheDocument();
        await act(async () => {
            vi.advanceTimersByTime(3000);
            for (let i = 0; i < 5; i += 1) await Promise.resolve();
        });
        expect(mockedRequest).toHaveBeenCalledWith(expect.stringContaining("since_seq=7"));
        const calls = mockedRequest.mock.calls.length;
        Object.defineProperty(document, "hidden", { configurable: true, value: true });
        await act(async () => {
            vi.advanceTimersByTime(3000);
        });
        expect(mockedRequest).toHaveBeenCalledTimes(calls);
        vi.useRealTimers();
    });

    it("shows a reload message when rollback loses the ETag race", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "admin/config/versions")
                return [
                    { id: "v1", time: "2026-01-01", actor: "a", route: "r", sha256: "12345678" },
                ];
            if (path.includes("/diff")) return [];
            throw Object.assign(new Error("changed"), {
                status: 412,
                body: { detail: "changed elsewhere" },
            });
        });
        render(<ConfigHistory />);
        fireEvent.click(await screen.findByText("a"));
        fireEvent.click(await screen.findByRole("button", { name: /roll back/i }));
        fireEvent.click(screen.getByRole("button", { name: /confirm rollback/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/changed elsewhere, reload/i);
    });

    it("reports a rate-limited support bundle", async () => {
        mockedRequest.mockResolvedValue({ items: [] });
        vi.mocked(download).mockRejectedValueOnce(
            Object.assign(new Error("rate"), { body: { detail: "support bundle rate limit" } }),
        );
        render(<Logs />);
        fireEvent.click(screen.getByRole("button", { name: "Pause" }));
        expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Resume" }));
        fireEvent.click(screen.getByRole("button", { name: /download support bundle/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent("support bundle rate limit");
    });

    it("reports a missing rollback precondition as a bug-level error", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "admin/config/versions")
                return [
                    { id: "v1", time: "2026-01-01", actor: "a", route: "r", sha256: "12345678" },
                ];
            if (path.includes("/diff")) return [];
            throw Object.assign(new Error("missing If-Match"), {
                status: 428,
                body: { detail: "If-Match is required" },
            });
        });
        render(<ConfigHistory />);
        fireEvent.click(await screen.findByText("a"));
        fireEvent.click(await screen.findByRole("button", { name: /roll back/i }));
        fireEvent.click(screen.getByRole("button", { name: /confirm rollback/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/bug-level error/i);
    });
});
