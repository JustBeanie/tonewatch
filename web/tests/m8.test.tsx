import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../src/App";

const preview = {
    imported: 1,
    skipped: 1,
    sections: [
        {
            name: "GoodPage",
            status: "imported",
            tone_set: {
                name: "Good Page",
                sequence: [{ freq_hz: 853, tol_pct: 2, min_s: 0.6 }],
            },
            notes: ["tone_tolerance missing: model default used"],
            errors: [],
        },
        {
            name: "BadPage",
            status: "skipped",
            tone_set: null,
            notes: [],
            errors: ["longtone must be a number"],
        },
    ],
};

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
    history.pushState({}, "", "/");
});

describe("TTD tone-set import", () => {
    it("renders the preview table and error rows", async () => {
        vi.spyOn(globalThis, "fetch").mockImplementation((input) =>
            String(input).includes("import/ttd") ? json(preview) : json([]),
        );
        render(<App />);
        fireEvent.click(screen.getByRole("link", { name: "Tone sets" }));
        fireEvent.change(await screen.findByLabelText("TTD config file"), {
            target: { files: [new File(["[GoodPage]"], "tones.cfg")] },
        });
        expect(
            await screen.findByRole("heading", { name: "TwoToneDetect import preview" }),
        ).toBeInTheDocument();
        expect(screen.getByText("853 Hz / 0.6 s")).toBeInTheDocument();
        expect(screen.getByText("longtone must be a number")).toBeInTheDocument();
    });

    it("requires confirmation before replacing tone sets", async () => {
        const fetcher = vi
            .spyOn(globalThis, "fetch")
            .mockImplementation((input, init) =>
                String(input).includes("import/ttd") && init?.method === "POST"
                    ? json(preview)
                    : json([]),
            );
        vi.spyOn(window, "confirm").mockReturnValue(false);
        render(<App />);
        fireEvent.click(screen.getByRole("link", { name: "Tone sets" }));
        fireEvent.change(await screen.findByLabelText("TTD config file"), {
            target: { files: [new File(["[GoodPage]"], "tones.cfg")] },
        });
        fireEvent.click(await screen.findByRole("button", { name: "Replace" }));
        expect(window.confirm).toHaveBeenCalled();
        await waitFor(() =>
            expect(
                fetcher.mock.calls.filter((call) => String(call[0]).includes("import/ttd")),
            ).toHaveLength(1),
        );
        expect(fetcher.mock.calls.at(-1)?.[0]).not.toContain("apply=true");
    });
});
