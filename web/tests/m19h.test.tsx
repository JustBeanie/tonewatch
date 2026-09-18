import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Audit } from "../src/features/admin/Audit";
import { Credentials } from "../src/features/admin/Credentials";
import { Maintenance } from "../src/features/admin/Maintenance";
import { formatBytes, formatDuration, formatExpiry } from "../src/features/admin/shared";

const response = (value: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(value), { status }));
afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
    history.pushState({}, "", "/");
});

describe("M19h credentials", () => {
    it("does not act when token and live-secret confirmations are cancelled", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch").mockReturnValue(response({ via: "direct" }));
        vi.spyOn(window, "confirm").mockReturnValue(false);
        render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        await screen.findByRole("button", { name: "Rotate API token" });
        fireEvent.click(screen.getByRole("button", { name: "Rotate API token" }));
        fireEvent.click(screen.getByRole("button", { name: "Rotate live secret" }));
        expect(fetcher).toHaveBeenCalledTimes(1);
    });
    it("shows a live-secret failure and rejects mismatched passwords", async () => {
        const fetcher = vi
            .spyOn(globalThis, "fetch")
            .mockImplementation((input) =>
                String(input).includes("auth/status")
                    ? response({ via: "direct" })
                    : response({ detail: "live secret unavailable" }, 503),
            );
        vi.spyOn(window, "confirm").mockReturnValue(true);
        render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        await screen.findByRole("button", { name: "Rotate live secret" });
        fireEvent.click(screen.getByRole("button", { name: "Rotate live secret" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("live secret unavailable");
        fireEvent.change(screen.getByLabelText("New password"), {
            target: { value: "long enough password" },
        });
        fireEvent.change(screen.getByLabelText("Confirm new password"), {
            target: { value: "different password" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Change UI password" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("do not match");
        expect(fetcher).toHaveBeenCalledTimes(2);
        expect(screen.getByLabelText("New password")).toHaveValue("");
    });
    it("shows a token once, never persists it, and drops it on remount", async () => {
        const storage = vi.spyOn(Storage.prototype, "setItem");
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            response(
                String(input).includes("auth/status")
                    ? { via: "direct" }
                    : { token: "secret-token", previous_valid_until: "later" },
            ),
        );
        vi.spyOn(window, "confirm").mockReturnValue(true);
        const view = render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        await waitFor(() =>
            expect(screen.getByRole("button", { name: "Rotate API token" })).toBeEnabled(),
        );
        fireEvent.click(screen.getByRole("button", { name: "Rotate API token" }));
        expect(await screen.findByDisplayValue("secret-token")).toBeInTheDocument();
        expect(storage).not.toHaveBeenCalledWith(
            expect.anything(),
            expect.stringContaining("secret-token"),
        );
        view.unmount();
        render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        expect(screen.queryByDisplayValue("secret-token")).not.toBeInTheDocument();
    });
    it("formats the previous token expiry as local time and remaining duration", async () => {
        vi.spyOn(Date, "now").mockReturnValue(1789996400000);
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            response(
                String(input).includes("auth/status")
                    ? { via: "direct" }
                    : { token: "secret-token", previous_valid_until: 1790000000 },
            ),
        );
        vi.spyOn(window, "confirm").mockReturnValue(true);
        render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        await screen.findByRole("button", { name: "Rotate API token" });
        fireEvent.click(screen.getByRole("button", { name: "Rotate API token" }));
        expect(await screen.findByText(/in 1h 00m/)).toBeInTheDocument();
        expect(screen.queryByText("1790000000", { exact: false })).not.toBeInTheDocument();
    });
    it("clears passwords and renders status-specific failures", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
            if (String(input).includes("auth/status")) return response({ via: "direct" });
            if (String(init?.body).includes("bad"))
                return response({ detail: "current password is incorrect" }, 403);
            return response({}, 200);
        });
        render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        await screen.findByRole("heading", { name: "Credentials" });
        fireEvent.change(screen.getByLabelText("Current password"), { target: { value: "bad" } });
        fireEvent.change(screen.getByLabelText("New password"), {
            target: { value: "long enough password" },
        });
        fireEvent.change(screen.getByLabelText("Confirm new password"), {
            target: { value: "long enough password" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Change UI password" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("Current password is incorrect");
        await waitFor(() => expect(screen.getByLabelText("Current password")).toHaveValue(""));
    });
    it("shows the ingress notice without actions", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(response({ via: "ingress" }));
        render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        expect(await screen.findByRole("status")).toHaveTextContent("direct access");
        expect(screen.queryByRole("button", { name: "Rotate API token" })).not.toBeInTheDocument();
    });
    it("clears fields after success and requests session revocation", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            response(String(input).includes("auth/status") ? { via: "direct" } : {}),
        );
        vi.spyOn(window, "confirm").mockReturnValue(true);
        render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        await screen.findByRole("heading", { name: "Credentials" });
        fireEvent.change(screen.getByLabelText("Current password"), {
            target: { value: "current" },
        });
        fireEvent.change(screen.getByLabelText("New password"), {
            target: { value: "long enough password" },
        });
        fireEvent.change(screen.getByLabelText("Confirm new password"), {
            target: { value: "long enough password" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Change UI password" }));
        await waitFor(() => expect(screen.getByLabelText("New password")).toHaveValue(""));
        fireEvent.click(screen.getByRole("button", { name: "Revoke all sessions" }));
        expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("including you"));
    });
    it("shows client validation and server 422/429 messages", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch");
        fetcher.mockImplementationOnce(() => response({ via: "direct" }));
        fetcher.mockImplementationOnce(() =>
            response({ detail: "too many password attempts" }, 429),
        );
        render(
            <MemoryRouter>
                <Credentials />
            </MemoryRouter>,
        );
        await screen.findByRole("heading", { name: "Credentials" });
        fireEvent.change(screen.getByLabelText("New password"), { target: { value: "short" } });
        fireEvent.click(screen.getByRole("button", { name: "Change UI password" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("at least 12");
        fireEvent.change(screen.getByLabelText("Current password"), {
            target: { value: "current" },
        });
        fireEvent.change(screen.getByLabelText("New password"), {
            target: { value: "long enough password" },
        });
        fireEvent.change(screen.getByLabelText("Confirm new password"), {
            target: { value: "long enough password" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Change UI password" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts");
    });
});

describe("M19h maintenance", () => {
    it("renders empty retention values and leaves run cancelled", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(
            response({ recordings: {}, calls: null, cad_incidents: null, discovered: null }),
        );
        vi.spyOn(window, "confirm").mockReturnValue(false);
        render(<Maintenance />);
        fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[0]!);
        expect((await screen.findAllByText("0", { exact: true })).length).toBe(4);
        expect(screen.getByText("—", { exact: true })).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Run now" }));
        expect(window.confirm).toHaveBeenCalled();
    });
    it("forces a fresh orphan preview after counts change and renders missing rows", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch");
        fetcher.mockImplementationOnce(() =>
            response({
                files: [],
                missing_rows: [{ id: 4, path: "missing.wav" }],
                invalid_rows: [],
                file_count: 0,
                row_count: 1,
                bytes: 0,
            }),
        );
        fetcher.mockImplementationOnce(() => response({ detail: "counts changed" }, 409));
        vi.spyOn(window, "confirm").mockReturnValue(true);
        render(<Maintenance />);
        fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[1]!);
        expect(await screen.findByText("Missing file: missing.wav")).toBeInTheDocument();
        fireEvent.click(screen.getByLabelText("Delete rows"));
        fireEvent.click(screen.getByRole("button", { name: "Apply" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("preview again");
        expect(screen.queryByRole("button", { name: "Apply" })).not.toBeInTheDocument();
    });
    it("handles a cancelled vacuum and a database request failure", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch");
        fetcher.mockImplementationOnce(() => response({ detail: "checkpoint failed" }, 500));
        vi.spyOn(window, "confirm").mockReturnValue(false);
        render(<Maintenance />);
        fireEvent.click(screen.getByRole("button", { name: "Checkpoint" }));
        expect(await screen.findByRole("alert")).toHaveTextContent("checkpoint failed");
        fireEvent.click(screen.getByRole("button", { name: "Vacuum" }));
        expect(fetcher).toHaveBeenCalledTimes(1);
    });
    it("requires retention preview, restates counts, and applies orphan counts", async () => {
        const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
        const calls: Array<{ url: string; init?: RequestInit | undefined }> = [];
        vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
            calls.push({ url: String(input), init });
            if (String(input).includes("retention/preview"))
                return response({
                    recordings: { files: 2, bytes: 2048 },
                    calls: 1,
                    cad_incidents: 2,
                    discovered: 3,
                });
            if (String(input).includes("orphans/preview"))
                return response({
                    files: [{ path: "old.mp3", bytes: 10 }],
                    missing_rows: [],
                    invalid_rows: [{ id: 7 }],
                    file_count: 1,
                    row_count: 0,
                    bytes: 10,
                });
            return response({ ok: true });
        });
        render(<Maintenance />);
        expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
        fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[0]!);
        expect((await screen.findAllByText("2")).length).toBeGreaterThan(0);
        fireEvent.click(screen.getByRole("button", { name: "Run now" }));
        expect(confirm).toHaveBeenCalledWith(expect.stringContaining("2 files"));
        await waitFor(() => expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled());
        fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[1]!);
        expect(await screen.findByRole("alert")).toHaveTextContent("invalid rows");
        fireEvent.click(screen.getByLabelText("Delete files"));
        fireEvent.click(screen.getByRole("button", { name: "Apply" }));
        await waitFor(() =>
            expect(calls.some((call) => call.url.includes("orphans/apply"))).toBe(true),
        );
        const apply = calls.find((call) => call.url.includes("orphans/apply"));
        expect(apply?.init?.body).toContain('"file_count":1');
    });
    it("renders readable maintenance conflicts and database sizes", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch");
        fetcher.mockImplementationOnce(() =>
            response({ detail: "maintenance operation already running" }, 409),
        );
        fetcher.mockImplementationOnce(() => response({ before_bytes: 20, after_bytes: 10 }));
        render(<Maintenance />);
        fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[0]!);
        expect(await screen.findByRole("alert")).toHaveTextContent("already running");
        fireEvent.click(screen.getByRole("button", { name: "Checkpoint" }));
        expect(await screen.findByText(/Before/)).toHaveTextContent("after");
    });
});

describe("M19h audit", () => {
    it("shows an empty audit state and readable request errors", async () => {
        const fetcher = vi.spyOn(globalThis, "fetch");
        fetcher.mockImplementationOnce(() => response({ items: [], next_cursor: null }));
        render(<Audit />);
        expect(await screen.findByText("No audit events.")).toBeInTheDocument();
        cleanup();
        fetcher.mockImplementationOnce(() => response({ detail: "audit unavailable" }, 503));
        render(<Audit />);
        expect(await screen.findByRole("alert")).toHaveTextContent("audit unavailable");
    });
    it("reads existing time filters from the URL and exercises formatter fallbacks", async () => {
        history.pushState(
            {},
            "",
            "/admin/audit?since=2026-01-01T00%3A00%3A00Z&until=2026-01-02T00%3A00%3A00Z",
        );
        vi.spyOn(globalThis, "fetch").mockReturnValue(response({ items: [], next_cursor: null }));
        render(<Audit />);
        expect(await screen.findByLabelText("Since")).toHaveValue("2026-01-01T00:00");
        expect(screen.getByLabelText("Until")).toHaveValue("2026-01-02T00:00");
        expect(formatExpiry("not an epoch")).toBe("—");
        expect(formatBytes(Number.NaN)).toBe("—");
        expect(formatDuration(Number.POSITIVE_INFINITY)).toBe("—");
    });
    it("serializes filters, appends keyset pages, shows diffs, and escapes fields", async () => {
        const first = {
            items: [
                {
                    id: 2,
                    created_at: "now",
                    actor: "<b>actor</b>",
                    event_type: "config_change",
                    resource: "config",
                    before: { a: "old" },
                    after: { a: "new" },
                    details: "<b>detail</b>",
                },
            ],
            next_cursor: "2",
        };
        const second = {
            items: [
                {
                    id: 1,
                    created_at: "later",
                    actor: "safe",
                    event_type: "login",
                    resource: "auth",
                    details: "ok",
                },
            ],
            next_cursor: null,
        };
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            response(String(input).includes("before_id=2") ? second : first),
        );
        render(<Audit />);
        expect(await screen.findByText("<b>actor</b>")).toBeInTheDocument();
        fireEvent.change(screen.getByLabelText("Actor"), { target: { value: "alice" } });
        expect(window.location.search).toContain("actor=alice");
        fireEvent.change(screen.getByLabelText("Since"), { target: { value: "2026-01-01T00:00" } });
        expect(window.location.search).toContain(
            `since=${encodeURIComponent(new Date("2026-01-01T00:00").toISOString())}`,
        );
        fireEvent.click(screen.getByText("<b>actor</b>"));
        expect(screen.getByText("Before / after")).toBeInTheDocument();
        expect(document.body.textContent).toContain("old");
        expect(document.body.textContent).toContain("<b>detail</b>");
        fireEvent.click(screen.getByRole("button", { name: "Load more" }));
        expect(await screen.findByText("later")).toBeInTheDocument();
        expect(screen.getAllByRole("row")).toHaveLength(4);
    });
});
