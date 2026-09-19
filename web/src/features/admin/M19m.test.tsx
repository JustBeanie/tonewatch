import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import { request } from "../../api/client";
import { Backup } from "./Backup";
import { Replay } from "./Replay";
import { download } from "./download";

vi.mock("../../api/client", () => ({ request: vi.fn() }));
vi.mock("./download", () => ({ download: vi.fn() }));
const mockedRequest = vi.mocked(request);

const config = {
    tone_sets: [
        {
            id: "fire",
            name: "Fire",
            enabled: true,
            sequence: [{ freq_hz: 1000, tol_pct: 1.5, min_s: 1, max_s: 3 }],
        },
    ],
    api_token: "secret-token",
};

function renderPage(page: React.ReactNode) {
    return render(<MemoryRouter>{page}</MemoryRouter>);
}

beforeEach(() => {
    mockedRequest.mockReset();
    vi.mocked(download).mockReset();
    vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => cleanup());

describe("M19m backup admin UI", () => {
    it("posts checkbox options exactly and disables while downloading", async () => {
        let resolveDownload: (() => void) | undefined;
        vi.mocked(download).mockImplementation(
            () => new Promise<void>((resolve) => (resolveDownload = resolve)),
        );
        renderPage(<Backup />);
        fireEvent.click(screen.getByLabelText("Include recordings"));
        fireEvent.click(screen.getByLabelText("Include credentials"));
        fireEvent.click(screen.getByRole("button", { name: /download backup/i }));
        expect(screen.getByRole("button", { name: /preparing/i })).toBeDisabled();
        expect(download).toHaveBeenCalledWith(
            "admin/backup",
            expect.objectContaining({
                method: "POST",
                body: JSON.stringify({ include_recordings: true, include_credentials: true }),
            }),
        );
        resolveDownload?.();
    });

    it("hides credentials through ingress and explains CLI-only restore", async () => {
        mockedRequest.mockResolvedValue({ via: "ingress" });
        renderPage(<Backup />);
        expect(
            await screen.findByText(/credentials are unavailable through ingress/i),
        ).toBeInTheDocument();
        expect(screen.queryByLabelText("Include credentials")).not.toBeInTheDocument();
        expect(screen.getByText("tonewatch backup restore FILE --dry-run")).toBeInTheDocument();
        expect(
            screen.getByText("tonewatch backup restore FILE", { exact: true }),
        ).toBeInTheDocument();
        expect(vi.mocked(fetch)).not.toHaveBeenCalled();
    });

    it.each([
        [409, "maintenance operation already running"],
        [429, "backup rate limit exceeded"],
        [403, "credential backups are not available through ingress"],
    ])("renders backup error %s", async (status, detail) => {
        vi.mocked(download).mockRejectedValue(
            Object.assign(new Error("failed"), { status, body: { detail } }),
        );
        renderPage(<Backup />);
        fireEvent.click(screen.getByRole("button", { name: /download backup/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    });
});

describe("M19m replay admin UI", () => {
    it("sends the edited current draft exactly and never saves config", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "config") return config;
            return {
                items: [],
                summary: {},
                audio_seconds: 0,
                audio_cap_seconds: 600,
                limitations: ["voice false positives"],
            };
        });
        renderPage(<Replay />);
        const frequency = await screen.findByLabelText("Fire tone 1 frequency");
        fireEvent.change(frequency, { target: { value: "1100" } });
        fireEvent.click(screen.getByRole("button", { name: /run replay/i }));
        await waitFor(() =>
            expect(mockedRequest).toHaveBeenCalledWith(
                "admin/replay",
                expect.objectContaining({ method: "POST" }),
            ),
        );
        const init = mockedRequest.mock.calls.find(([path]) => path === "admin/replay")?.[1];
        expect(init?.body).toBe(
            JSON.stringify({
                draft: {
                    tone_sets: [
                        {
                            id: "fire",
                            name: "Fire",
                            enabled: true,
                            sequence: [{ freq_hz: 1100, tol_pct: 1.5, min_s: 1, max_s: 3 }],
                        },
                    ],
                    api_token: "secret-token",
                },
                calls: { last_n: 1 },
                uploads: [],
            }),
        );
        expect(mockedRequest).not.toHaveBeenCalledWith(
            "config",
            expect.objectContaining({ method: "PUT" }),
        );
    });

    it("uploads WAVs, renders classifications and limitations safely", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "config") return config;
            if (path === "admin/replay/uploads") return { id: "upload-1" };
            return {
                items: [
                    {
                        id: "x",
                        recorded: [],
                        draft: [{ toneset_id: "fire", detection_times: [1.25] }],
                        classification: "new_detection",
                        reason: "<b>review</b>",
                    },
                ],
                summary: { new_detection: 1 },
                audio_seconds: 2,
                audio_cap_seconds: 600,
                limitations: ["uploads test detection"],
            };
        });
        renderPage(<Replay />);
        await screen.findByText("Fire");
        fireEvent.change(screen.getByLabelText("Replay WAV files"), {
            target: { files: [new File(["RIFF"], "test.wav", { type: "audio/wav" })] },
        });
        expect(await screen.findByText(/upload-1/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /run replay/i }));
        expect(await screen.findByText("new detection")).toBeInTheDocument();
        expect(screen.getByText("<b>review</b>")).toBeInTheDocument();
        expect(screen.getByText("uploads test detection")).toBeInTheDocument();
    });

    it("offers re-upload for an expired upload and supports removing uploads", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "config") return config;
            if (path === "admin/replay/uploads") return { id: "expired-1" };
            throw Object.assign(new Error("expired"), {
                status: 404,
                body: { detail: "replay upload not found" },
            });
        });
        renderPage(<Replay />);
        await screen.findByText("Fire");
        fireEvent.change(screen.getByLabelText("Replay WAV files"), {
            target: { files: [new File(["RIFF"], "expired.wav", { type: "audio/wav" })] },
        });
        expect(await screen.findByText(/expired-1/)).toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: "Remove" }));
        expect(screen.queryByText(/expired-1/)).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole("button", { name: /run replay/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/re-upload/i);
    });

    it("renders a readable oversized upload error and permits uploads-only replay", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "config") return config;
            throw Object.assign(new Error("too large"), {
                status: 413,
                body: { detail: "upload too large" },
            });
        });
        renderPage(<Replay />);
        await screen.findByText("Fire");
        fireEvent.click(screen.getByLabelText("Use last N calls"));
        fireEvent.change(screen.getByLabelText("Replay WAV files"), {
            target: { files: [new File(["RIFF"], "large.wav", { type: "audio/wav" })] },
        });
        expect(await screen.findByRole("alert")).toHaveTextContent("upload too large");
    });

    it("accepts an advanced JSON draft and renders an empty result", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "config") return config;
            return {
                items: [],
                summary: {},
                audio_seconds: 0,
                audio_cap_seconds: 600,
                limitations: [],
            };
        });
        renderPage(<Replay />);
        await screen.findByText("Fire");
        fireEvent.click(screen.getByLabelText("Use last N calls"));
        fireEvent.change(screen.getByLabelText("Draft YAML or JSON"), {
            target: { value: JSON.stringify({ tone_sets: [] }) },
        });
        fireEvent.click(screen.getByRole("button", { name: /run replay/i }));
        expect(await screen.findByText("No calls or uploads matched.")).toBeInTheDocument();
    });

    it("reports malformed advanced draft text", async () => {
        mockedRequest.mockResolvedValue(config);
        renderPage(<Replay />);
        await screen.findByText("Fire");
        fireEvent.change(screen.getByLabelText("Draft YAML or JSON"), {
            target: { value: "not json" },
        });
        fireEvent.click(screen.getByRole("button", { name: /run replay/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/unexpected token/i);
    });

    it("renders unknown summary and item values as text", async () => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "config") return config;
            return {
                items: [{ id: "mystery", classification: "custom", reason: undefined }],
                summary: { custom: 1 },
                audio_seconds: 1,
                audio_cap_seconds: 600,
                limitations: [],
            };
        });
        renderPage(<Replay />);
        await screen.findByText("Fire");
        fireEvent.click(screen.getByRole("button", { name: /run replay/i }));
        expect(await screen.findByText("custom")).toBeInTheDocument();
        expect(screen.getByText("mystery")).toBeInTheDocument();
    });

    it.each([
        [422, "draft.tone_sets.0.sequence.0.freq_hz"],
        [429, "replay already in progress"],
    ])("renders replay error %s", async (status, detail) => {
        mockedRequest.mockImplementation(async (path) => {
            if (path === "config") return config;
            throw Object.assign(new Error("failed"), { status, body: { detail } });
        });
        renderPage(<Replay />);
        await screen.findByText("Fire");
        fireEvent.click(screen.getByRole("button", { name: /run replay/i }));
        expect(await screen.findByRole("alert")).toHaveTextContent(detail);
    });
});
