import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
    LivePlayer,
    Diagnostics,
    Source,
    SquelchEditor,
} from "../src/features/sources/SourceControls";
import { Settings } from "../src/features/settings/Settings";

const source: Source = { id: "radio", name: "Radio", type: "file", live_stream_enabled: true };
const level = {
    type: "ChannelLevel",
    data: {
        source_id: "radio",
        rms_dbfs: -12,
        squelch_level_dbfs: -11,
        squelch_open: true,
        open_dbfs_effective: -40,
        close_dbfs_effective: -45,
    },
};
const json = (value: unknown, status = 200) =>
    Promise.resolve(new Response(JSON.stringify(value), { status }));

afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
});

describe("UI1 live and squelch controls", () => {
    it("mints, plays, copies and stops live audio", async () => {
        const consoleSpies = [
            vi.spyOn(console, "log").mockImplementation(() => undefined),
            vi.spyOn(console, "info").mockImplementation(() => undefined),
            vi.spyOn(console, "warn").mockImplementation(() => undefined),
            vi.spyOn(console, "error").mockImplementation(() => undefined),
        ];
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            String(input).includes("live-url")
                ? json({
                      url: "https://example/live.mp3?t=secret",
                      expires_at: Math.floor(Date.now() / 1000) + 600,
                  })
                : json({ ...source, live_listeners: 1 }),
        );
        Object.defineProperty(navigator, "clipboard", {
            configurable: true,
            value: { writeText: vi.fn() },
        });
        const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
        render(
            <LivePlayer
                source={source}
                message={{
                    type: "live_listeners_changed",
                    data: { source_id: "radio", source_listeners: 1 },
                }}
            />,
        );
        fireEvent.click(screen.getByRole("button", { name: "Listen live" }));
        const audio = await screen.findByLabelText("Live audio for Radio");
        await waitFor(() =>
            expect(audio).toHaveAttribute("src", expect.stringContaining("live.mp3")),
        );
        await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("1 listener"));
        expect(play).toHaveBeenCalled();
        fireEvent.click(screen.getByRole("button", { name: "Copy player URL" }));
        expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
            expect.stringContaining("secret"),
        );
        const consoleCalls = consoleSpies.flatMap((spy) => spy.mock.calls).flat();
        const serializedConsoleCalls = JSON.stringify(consoleCalls);
        expect(serializedConsoleCalls).not.toContain("https://example/live.mp3");
        expect(serializedConsoleCalls).not.toContain("secret");
        fireEvent.click(screen.getByRole("button", { name: "Stop live" }));
        expect(audio).toHaveAttribute("src", "");
    });
    it("explains disabled and capacity errors", async () => {
        const disabled = { ...source, live_stream_enabled: false };
        render(<LivePlayer source={disabled} message={undefined} />);
        expect(screen.getByRole("button", { name: "Listen live" })).toBeDisabled();
        expect(screen.getByText(/disabled for this source/)).toBeInTheDocument();
        vi.restoreAllMocks();
        vi.spyOn(globalThis, "fetch").mockReturnValue(json({}, 503));
        render(<LivePlayer source={source} message={undefined} />);
        fireEvent.click(screen.getAllByRole("button", { name: "Listen live" })[1]!);
        expect(await screen.findByRole("alert")).toHaveTextContent(/capacity is full/);
    });
    it("uses the documented clipboard fallback", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(
            json({
                url: "https://example/live.mp3",
                expires_at: Math.floor(Date.now() / 1000) + 60,
            }),
        );
        Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
        const copy = vi.fn().mockReturnValue(true);
        Object.defineProperty(document, "execCommand", { configurable: true, value: copy });
        render(<LivePlayer source={source} message={undefined} />);
        fireEvent.click(screen.getByRole("button", { name: "Listen live" }));
        fireEvent.click(await screen.findByRole("button", { name: "Copy player URL" }));
        expect(copy).toHaveBeenCalledWith("copy");
    });
    it("handles a non-cap mint failure without throwing", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValue(json({}, 500));
        render(<LivePlayer source={source} message={undefined} />);
        fireEvent.click(screen.getByRole("button", { name: "Listen live" }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/Unable to start/);
    });
    it("loads and saves the live-stream setting", async () => {
        const fetcher = vi
            .spyOn(globalThis, "fetch")
            .mockImplementation((input, init) =>
                String(input).includes("config") && init?.method === "PUT"
                    ? json({ live_stream: { enabled: true } })
                    : String(input).includes("config")
                      ? json({ live_stream: { enabled: false }, sources: [] })
                      : json({ authenticated: true, password_required: false }),
            );
        render(<Settings />);
        const toggle = await screen.findByRole("checkbox", { name: /Enable live streaming/ });
        fireEvent.click(toggle);
        await waitFor(() =>
            expect(fetcher).toHaveBeenCalledWith(
                expect.stringContaining("config"),
                expect.objectContaining({ method: "PUT" }),
            ),
        );
    });
    it("shows the four mode field sets and validation", () => {
        render(<SquelchEditor source={source} message={level} onSaved={vi.fn()} />);
        const mode = screen.getByRole("combobox", { name: "Mode" });
        expect(screen.queryByRole("spinbutton", { name: "Open dBFS" })).not.toBeInTheDocument();
        fireEvent.change(mode, { target: { value: "level" } });
        expect(screen.getByRole("spinbutton", { name: "Open dBFS" })).toBeInTheDocument();
        fireEvent.change(mode, { target: { value: "noise_floor" } });
        expect(screen.getByRole("spinbutton", { name: "Floor margin (dB)" })).toBeInTheDocument();
        fireEvent.change(mode, { target: { value: "auto" } });
        expect(screen.getByRole("spinbutton", { name: "Auto window (s)" })).toBeInTheDocument();
        fireEvent.change(mode, { target: { value: "level" } });
        fireEvent.change(screen.getByRole("spinbutton", { name: "Open dBFS" }), {
            target: { value: "-60" },
        });
        fireEvent.change(screen.getByRole("spinbutton", { name: "Close dBFS" }), {
            target: { value: "-20" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Save squelch" }));
        expect(
            screen.getAllByRole("alert").find((item) => item.textContent?.includes("less than")),
        ).toBeInTheDocument();
        expect(screen.getByRole("img", { name: /Squelch meter/ })).toBeInTheDocument();
    });
    it("calibrates without saving and renders diagnostics tooltips", async () => {
        const saved = vi.fn();
        vi.spyOn(globalThis, "fetch").mockReturnValue(
            json({ suggested: { open_dbfs: -30, close_dbfs: -38 } }),
        );
        render(<SquelchEditor source={source} message={level} onSaved={saved} />);
        fireEvent.change(screen.getByRole("combobox", { name: "Mode" }), {
            target: { value: "level" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Set from noise floor" }));
        await waitFor(() =>
            expect(screen.getByRole("spinbutton", { name: "Open dBFS" })).toHaveValue(-30),
        );
        expect(saved).not.toHaveBeenCalled();
        const diagnostic = {
            ...source,
            calibrating: true,
            stuck_open: false,
            chatter: true,
            noise_floor_dbfs: -70,
            open_dbfs_effective: -40,
            close_dbfs_effective: -45,
            transitions_per_min: 3,
            squelch_mode_effective: "auto",
        };
        render(<Diagnostics source={diagnostic} />);
        expect(screen.getByTitle(/collecting/)).toBeInTheDocument();
        expect(screen.getByTitle(/transitioning/)).toBeInTheDocument();
    });
    it("surfaces calibration and save validation responses", async () => {
        vi.spyOn(globalThis, "fetch").mockReturnValueOnce(json({}, 409));
        render(<SquelchEditor source={source} message={level} onSaved={vi.fn()} />);
        fireEvent.change(screen.getByRole("combobox", { name: "Mode" }), {
            target: { value: "level" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Set from noise floor" }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/not running/);
        cleanup();
        vi.restoreAllMocks();
        vi.spyOn(globalThis, "fetch").mockReturnValueOnce(json({}, 429));
        render(<SquelchEditor source={source} message={level} onSaved={vi.fn()} />);
        fireEvent.change(screen.getByRole("combobox", { name: "Mode" }), {
            target: { value: "level" },
        });
        fireEvent.click(screen.getByRole("button", { name: "Set from noise floor" }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/already running/);
        cleanup();
        vi.restoreAllMocks();
        vi.spyOn(globalThis, "fetch").mockReturnValueOnce(
            json(
                { detail: [{ loc: ["body", "squelch", "open_dbfs"], msg: "bad threshold" }] },
                422,
            ),
        );
        render(
            <SquelchEditor
                source={{
                    ...source,
                    squelch: {
                        mode: "level",
                        open_dbfs: -40,
                        close_dbfs: -45,
                        attack_ms: 50,
                        hang_ms: 1500,
                        floor_margin_db: 10,
                        auto_window_s: 300,
                        auto_min_samples_s: 30,
                        auto_k: 1.5,
                        min_margin_db: 6,
                        max_margin_db: 25,
                        stuck_open_s: 600,
                        max_transitions_per_min: 20,
                    },
                }}
                message={level}
                onSaved={vi.fn()}
            />,
        );
        fireEvent.click(screen.getByRole("button", { name: "Save squelch" }));
        expect(await screen.findByRole("alert")).toHaveTextContent(/bad threshold/);
    });
});
