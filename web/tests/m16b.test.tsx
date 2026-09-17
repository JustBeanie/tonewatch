import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgencyForm, errorText } from "../src/features/agencies/AgencyForm";
import { MapPage } from "../src/features/map/MapPage";
import { CallDetail, Calls } from "../src/features/calls/Calls";
import { MemoryRouter, Route, Routes } from "react-router";
import { Agencies } from "../src/features/agencies/Agencies";
import { MapCanvas } from "../src/features/map/MapCanvas";
import { Dashboard } from "../src/features/dashboard/Dashboard";

const request = vi.hoisted(() => vi.fn());
vi.mock("../src/api/client", () => ({ request }));
const wsState = vi.hoisted(() => ({
    event: undefined as { type: string; data?: Record<string, unknown> } | undefined,
    handler: undefined as
        ((message: { type: string; data?: Record<string, unknown> }) => void) | undefined,
}));
vi.mock("../src/lib/ws", () => ({
    useSubscription: () => wsState.event,
    useWsEvents: (_topic: string, handler: typeof wsState.handler) => {
        wsState.handler = handler;
    },
    useConnectionStatus: () => "connected",
}));
const routed = (element: React.ReactElement) => (
    <MemoryRouter initialEntries={[window.location.pathname + window.location.search]}>
        {element}
    </MemoryRouter>
);
afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    wsState.event = undefined;
    wsState.handler = undefined;
});

describe("M16b agency editor", () => {
    it("formats list, string, and network save errors", () => {
        expect(
            errorText({
                body: {
                    detail: [{ loc: ["body", "coverage"], msg: "must be a closed ring" }],
                },
            }),
        ).toBe("coverage: must be a closed ring");
        expect(errorText({ body: { detail: "coverage is invalid" } })).toBe("coverage is invalid");
        expect(errorText(new Error("Failed to fetch"))).toBe("Failed to fetch");
        expect(errorText({})).toBe("Unable to save agency.");
        expect(errorText({ body: { detail: [{ msg: "invalid" }] } })).toBe("invalid");
    });

    it("sets coordinates from the map wrapper click", async () => {
        request.mockResolvedValueOnce([]);
        render(routed(<AgencyForm />));
        fireEvent.change(screen.getByLabelText("ID"), { target: { value: "alpha" } });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Alpha" } });
        fireEvent.change(screen.getByLabelText("Short name"), { target: { value: "A" } });
        fireEvent.change(screen.getByLabelText("ID"), { target: { value: "alpha" } });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Alpha" } });
        fireEvent.change(screen.getByLabelText("Short name"), { target: { value: "A" } });
        fireEvent.click(screen.getByRole("button", { name: "Place on map" }));
        fireEvent.click(screen.getByTestId("agency-map-click"));
        expect(screen.getByLabelText("Latitude")).toHaveValue(40.1);
        expect(screen.getByLabelText("Longitude")).toHaveValue(-105.2);
        fireEvent.click(screen.getByTestId("map-marker-draft"));
    });

    it("updates the marker when coordinates are typed and serializes CAD tags", async () => {
        request.mockResolvedValueOnce([]);
        render(routed(<AgencyForm />));
        fireEvent.change(screen.getByLabelText("ID"), { target: { value: "alpha" } });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Alpha" } });
        fireEvent.change(screen.getByLabelText("Short name"), { target: { value: "A" } });
        fireEvent.change(screen.getByLabelText("Latitude"), { target: { value: "41" } });
        fireEvent.change(screen.getByLabelText("Longitude"), { target: { value: "-106" } });
        fireEvent.change(screen.getByLabelText("CAD names"), { target: { value: " FIRE1" } });
        fireEvent.keyDown(screen.getByLabelText("CAD names"), { key: "Enter" });
        fireEvent.click(screen.getByRole("button", { name: /FIRE1/ }));
        fireEvent.change(screen.getByLabelText("CAD names"), { target: { value: " FIRE1" } });
        fireEvent.keyDown(screen.getByLabelText("CAD names"), { key: "Enter" });
        expect(screen.getByTestId("agency-marker")).toHaveAttribute("data-lat", "41");
        fireEvent.click(screen.getByRole("button", { name: "Save agency" }));
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "agencies",
                expect.objectContaining({ method: "POST" }),
            ),
        );
        const last = request.mock.calls.at(-1);
        expect(last).toBeDefined();
        expect(JSON.parse(last?.[1].body).cad_names).toEqual(["FIRE1"]);
    });

    it("shows the server validation message for invalid coverage", async () => {
        request.mockResolvedValueOnce([]).mockRejectedValueOnce(
            Object.assign(new Error("bad"), {
                status: 422,
                body: { detail: "coverage must be a GeoJSON Polygon or MultiPolygon" },
            }),
        );
        render(routed(<AgencyForm />));
        fireEvent.change(screen.getByLabelText("ID"), { target: { value: "alpha" } });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Alpha" } });
        fireEvent.change(screen.getByLabelText("Short name"), { target: { value: "A" } });
        fireEvent.change(screen.getByLabelText("Coverage GeoJSON"), { target: { value: "{}" } });
        fireEvent.submit(screen.getByRole("button", { name: "Save agency" }).closest("form")!);
        expect(await screen.findByRole("alert")).toHaveTextContent(
            "coverage must be a GeoJSON Polygon or MultiPolygon",
        );
    });

    it("adds a station from map placement and reads uploaded coverage", async () => {
        request.mockResolvedValueOnce([]);
        render(routed(<AgencyForm />));
        fireEvent.change(screen.getByLabelText("Station name"), { target: { value: "Station 1" } });
        fireEvent.click(screen.getByRole("button", { name: "Add station at map click" }));
        fireEvent.click(screen.getByTestId("agency-map-click"));
        expect(screen.getByText(/Station 1/)).toBeInTheDocument();
        const file = new File(['{"type":"Polygon"}'], "coverage.geojson", {
            type: "application/geo+json",
        });
        fireEvent.change(screen.getByLabelText("Upload .geojson"), { target: { files: [file] } });
        await waitFor(() =>
            expect(screen.getByLabelText("Coverage GeoJSON")).toHaveValue('{"type":"Polygon"}'),
        );
    });

    it("rejects malformed local coverage JSON before sending", async () => {
        request.mockResolvedValueOnce([]);
        render(routed(<AgencyForm />));
        fireEvent.change(screen.getByLabelText("ID"), { target: { value: "alpha" } });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Alpha" } });
        fireEvent.change(screen.getByLabelText("Short name"), { target: { value: "A" } });
        fireEvent.change(screen.getByLabelText("Coverage GeoJSON"), { target: { value: "{" } });
        fireEvent.submit(screen.getByRole("button", { name: "Save agency" }).closest("form")!);
        expect(await screen.findByRole("alert")).toHaveTextContent("Coverage must be valid JSON");
    });

    it("toggles a linked tone set", async () => {
        request
            .mockResolvedValueOnce([{ id: "tone", name: "Tone", agency_id: null }])
            .mockResolvedValueOnce({})
            .mockResolvedValueOnce({ id: "tone", name: "Tone", sequence: [{ freq_hz: 1000 }] })
            .mockResolvedValueOnce({});
        render(routed(<AgencyForm />));
        const checkbox = await screen.findByLabelText("Tone");
        fireEvent.click(checkbox);
        expect(checkbox).toBeChecked();
        fireEvent.change(screen.getByLabelText("ID"), { target: { value: "alpha" } });
        fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Alpha" } });
        fireEvent.change(screen.getByLabelText("Short name"), { target: { value: "A" } });
        fireEvent.submit(screen.getByRole("button", { name: "Save agency" }).closest("form")!);
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "tonesets/tone",
                expect.objectContaining({ method: "PUT" }),
            ),
        );
        fireEvent.click(checkbox);
        expect(checkbox).not.toBeChecked();
        fireEvent.keyDown(screen.getByLabelText("CAD names"), { key: "Escape" });
        fireEvent.change(screen.getByLabelText("Upload .geojson"), { target: { files: [] } });
    });
});

describe("M16b map", () => {
    it("renders features, notices when tiles are off, and pulses on matching call", async () => {
        request.mockImplementation((path: string) =>
            path === "agencies.geojson"
                ? Promise.resolve({
                      type: "FeatureCollection",
                      features: [
                          {
                              type: "Feature",
                              geometry: { type: "Point", coordinates: [-105, 40] },
                              properties: {
                                  id: "a",
                                  name: "Alpha",
                                  kind: "fire",
                                  color: "#ff0000",
                              },
                          },
                          {
                              type: "Feature",
                              geometry: {
                                  type: "Polygon",
                                  coordinates: [
                                      [
                                          [0, 0],
                                          [1, 0],
                                          [1, 1],
                                          [0, 0],
                                      ],
                                  ],
                              },
                              properties: {
                                  id: "a",
                                  name: "Alpha",
                                  kind: "fire",
                                  color: "#ff0000",
                              },
                          },
                      ],
                  })
                : path === "map-config"
                  ? Promise.resolve({ map: { tile_url: "", attribution: "" } })
                  : Promise.resolve({ items: [] }),
        );
        render(routed(<MapPage />));
        expect(await screen.findByText(/Tiles are disabled/)).toBeInTheDocument();
        expect(screen.getByTestId("map-marker-a")).toBeInTheDocument();
        expect(screen.getByTestId("map-polygon-a")).toBeInTheDocument();
    });

    it("uses static highlight for reduced motion", async () => {
        vi.stubGlobal("matchMedia", () => ({
            matches: true,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
        }));
        request.mockResolvedValue({ type: "FeatureCollection", features: [] });
        render(routed(<MapPage />));
        expect(await screen.findByTestId("map-canvas")).toHaveAttribute(
            "data-reduced-motion",
            "true",
        );
    });

    it("adds and removes a pulse using the call id", async () => {
        const feature = {
            type: "Feature" as const,
            geometry: { type: "Point", coordinates: [-105, 40] },
            properties: { id: "a", name: "Alpha", color: "#ff0000" },
        };
        request.mockImplementation((path: string) =>
            path === "agencies.geojson"
                ? Promise.resolve({ features: [feature] })
                : Promise.resolve({ map: { tile_url: "" } }),
        );
        render(routed(<MapPage />));
        await screen.findByTestId("map-marker-a");
        vi.useFakeTimers();
        act(() =>
            wsState.handler?.({
                type: "ToneDetected",
                data: { call_id: "call-1", agency: { id: "a" } },
            }),
        );
        expect(screen.getByTestId("map-marker-a")).toHaveClass("marker-pulse");
        act(() => wsState.handler?.({ type: "CallClosed", data: { call_id: "call-1" } }));
        expect(screen.getByTestId("map-marker-a")).toHaveClass("marker-pulse");
        act(() => vi.advanceTimersByTime(7900));
        expect(screen.getByTestId("map-marker-a")).toHaveClass("marker-pulse");
        act(() => vi.advanceTimersByTime(200));
        expect(screen.getByTestId("map-marker-a")).not.toHaveClass("marker-pulse");
    });

    it("ends a late-closed pulse immediately after the call closes", async () => {
        const feature = {
            type: "Feature" as const,
            geometry: { type: "Point", coordinates: [-105, 40] },
            properties: { id: "a", name: "Alpha", color: "#ff0000" },
        };
        request.mockImplementation((path: string) =>
            path === "agencies.geojson"
                ? Promise.resolve({ features: [feature] })
                : Promise.resolve({ map: { tile_url: "" } }),
        );
        render(routed(<MapPage />));
        await screen.findByTestId("map-marker-a");
        vi.useFakeTimers();
        act(() =>
            wsState.handler?.({
                type: "ToneDetected",
                data: { call_id: "late", agency: { id: "a" } },
            }),
        );
        act(() => vi.advanceTimersByTime(20000));
        act(() => wsState.handler?.({ type: "CallClosed", data: { call_id: "late" } }));
        expect(screen.getByTestId("map-marker-a")).not.toHaveClass("marker-pulse");
    });

    it("keeps an overlapping agency pulse until every call is closed and elapsed", async () => {
        const feature = {
            type: "Feature" as const,
            geometry: { type: "Point", coordinates: [-105, 40] },
            properties: { id: "a", name: "Alpha", color: "#ff0000" },
        };
        request.mockImplementation((path: string) =>
            path === "agencies.geojson"
                ? Promise.resolve({ features: [feature] })
                : Promise.resolve({ map: { tile_url: "" } }),
        );
        render(routed(<MapPage />));
        await screen.findByTestId("map-marker-a");
        vi.useFakeTimers();
        act(() =>
            wsState.handler?.({
                type: "ToneDetected",
                data: { call_id: "one", agency: { id: "a" } },
            }),
        );
        act(() => vi.advanceTimersByTime(2000));
        act(() =>
            wsState.handler?.({
                type: "ToneDetected",
                data: { call_id: "two", agency: { id: "a" } },
            }),
        );
        act(() => wsState.handler?.({ type: "CallClosed", data: { call_id: "one" } }));
        act(() => vi.advanceTimersByTime(6000));
        expect(screen.getByTestId("map-marker-a")).toHaveClass("marker-pulse");
        act(() => wsState.handler?.({ type: "CallClosed", data: { call_id: "two" } }));
        expect(screen.getByTestId("map-marker-a")).toHaveClass("marker-pulse");
        act(() => vi.advanceTimersByTime(2000));
        expect(screen.getByTestId("map-marker-a")).not.toHaveClass("marker-pulse");
    });

    it("clears pulse timers when the map unmounts", async () => {
        const feature = {
            type: "Feature" as const,
            geometry: { type: "Point", coordinates: [-105, 40] },
            properties: { id: "a", name: "Alpha", color: "#ff0000" },
        };
        request.mockImplementation((path: string) =>
            path === "agencies.geojson"
                ? Promise.resolve({ features: [feature] })
                : Promise.resolve({ map: { tile_url: "" } }),
        );
        const view = render(routed(<MapPage />));
        await screen.findByTestId("map-marker-a");
        vi.useFakeTimers();
        act(() =>
            wsState.handler?.({
                type: "ToneDetected",
                data: { call_id: "unmount", agency: { id: "a" } },
            }),
        );
        view.unmount();
        act(() => vi.advanceTimersByTime(8000));
    });

    it("loads the selected agency card and its last calls", async () => {
        const feature = {
            type: "Feature" as const,
            geometry: { type: "Point", coordinates: [-105, 40] },
            properties: { id: "a", name: "Alpha", kind: "fire", color: "#ff0000" },
        };
        request.mockImplementation((path: string) =>
            path === "agencies.geojson"
                ? Promise.resolve({ features: [feature] })
                : path.startsWith("calls?")
                  ? Promise.resolve({ items: [{ id: "c1", started_at: "today", status: "open" }] })
                  : Promise.resolve({ map: { tile_url: "" } }),
        );
        render(routed(<MapPage />));
        await screen.findByTestId("map-marker-a");
        fireEvent.click(screen.getAllByRole("button", { name: "Alpha" })[1]!);
        expect(await screen.findByText("Last 5 calls")).toBeInTheDocument();
        expect(await screen.findByText("today · open")).toBeInTheDocument();
    });

    it("accepts a configured tile layer", async () => {
        request.mockImplementation((path: string) =>
            path === "agencies.geojson"
                ? Promise.resolve({ features: [] })
                : Promise.resolve({
                      map: {
                          tile_url: "https://tiles.example/{z}/{x}/{y}.png",
                          attribution: "Tiles",
                      },
                  }),
        );
        render(routed(<MapPage />));
        expect(await screen.findByTestId("map-canvas")).toBeInTheDocument();
        expect(screen.queryByText(/Tiles are disabled/)).not.toBeInTheDocument();
    });

    it("keeps same-tick start and close events pulsing for the minimum duration", async () => {
        const feature = {
            type: "Feature" as const,
            geometry: { type: "Point", coordinates: [-105, 40] },
            properties: { id: "a", name: "Alpha", color: "#ff0000" },
        };
        request.mockImplementation((path: string) =>
            path === "agencies.geojson"
                ? Promise.resolve({ features: [feature] })
                : Promise.resolve({ map: { tile_url: "" } }),
        );
        render(routed(<MapPage />));
        await screen.findByTestId("map-marker-a");
        vi.useFakeTimers();
        act(() => {
            wsState.handler?.({
                type: "ToneDetected",
                data: { call_id: "same", agency: { id: "a" } },
            });
            wsState.handler?.({ type: "CallClosed", data: { call_id: "same" } });
        });
        act(() => vi.advanceTimersByTime(7900));
        expect(screen.getByTestId("map-marker-a")).toHaveClass("marker-pulse");
        act(() => vi.advanceTimersByTime(200));
        expect(screen.getByTestId("map-marker-a")).not.toHaveClass("marker-pulse");
    });
});

describe("M16b lossless event consumers", () => {
    it("adds both same-tick call events to the dashboard feed", async () => {
        request.mockImplementation((path: string) =>
            path === "calls?limit=50"
                ? Promise.resolve({ items: [] })
                : path === "sources"
                  ? Promise.resolve([])
                  : Promise.resolve({ items: [] }),
        );
        render(routed(<Dashboard />));
        await waitFor(() => expect(request).toHaveBeenCalledWith("sources"));
        act(() => {
            wsState.handler?.({
                type: "ToneDetected",
                data: { id: "call-one", source_id: "radio", status: "open", started_at: "one" },
            });
            wsState.handler?.({
                type: "CallClosed",
                data: { id: "call-two", source_id: "radio", status: "closed", started_at: "two" },
            });
        });
        expect(screen.getByText("radio · open · one")).toBeInTheDocument();
        expect(screen.getByText("radio · closed · two")).toBeInTheDocument();
    });

    it("shows the agency snapshot in call detail", async () => {
        window.history.pushState({}, "", "/calls/call-one");
        request.mockResolvedValue({
            id: "call-one",
            started_at: "today",
            source_id: "test",
            status: "closed",
            tone_sets: [
                {
                    toneset_id: "fixture-page",
                    detected_at: "today",
                    agency: { id: "a", name: "Alpha", kind: "fire" },
                },
            ],
            recordings: [],
            alert_attempts: [],
        });
        render(
            <MemoryRouter initialEntries={["/calls/call-one"]}>
                <Routes>
                    <Route path="/calls/:id" element={<CallDetail />} />
                </Routes>
            </MemoryRouter>,
        );
        expect(await screen.findByText(/Alpha \(fire\)/)).toBeInTheDocument();
    });
});

describe("M16b agency list", () => {
    it("counts linked tones and confirms deletion", async () => {
        const agency = { id: "alpha", name: "Alpha", kind: "fire", location: { lat: 1, lon: 2 } };
        request.mockImplementation((path: string) =>
            path === "agencies"
                ? Promise.resolve([agency])
                : Promise.resolve([{ id: "tone", agency_id: "alpha" }]),
        );
        render(routed(<Agencies />));
        expect(await screen.findByText("Alpha")).toBeInTheDocument();
        expect(screen.getByRole("cell", { name: "1" })).toBeInTheDocument();
        vi.spyOn(window, "confirm").mockReturnValue(false);
        fireEvent.click(screen.getByRole("button", { name: "Delete" }));
        expect(request).toHaveBeenCalledTimes(2);
    });

    it("deletes after confirmation and reloads the list", async () => {
        const agency = { id: "alpha", name: "Alpha", kind: "fire", location: { lat: 1, lon: 2 } };
        request.mockImplementation((path: string) =>
            path === "agencies" ? Promise.resolve([agency]) : Promise.resolve([]),
        );
        render(routed(<Agencies />));
        await screen.findByText("Alpha");
        vi.spyOn(window, "confirm").mockReturnValue(true);
        fireEvent.click(screen.getByRole("button", { name: "Delete" }));
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith("agencies/alpha", { method: "DELETE" }),
        );
    });
});

describe("M16b map wrapper", () => {
    it("keeps unsupported geometries accessible without drawing them", () => {
        render(
            <MapCanvas
                features={[
                    {
                        type: "Feature",
                        geometry: { type: "LineString", coordinates: [] },
                        properties: { id: "line" },
                    },
                ]}
            />,
        );
        expect(screen.getByTestId("map-canvas")).toBeInTheDocument();
        expect(screen.queryByTestId("map-marker-line")).not.toBeInTheDocument();
    });
});

describe("M16b calls filter", () => {
    it("requests calls with agency_id", async () => {
        request.mockResolvedValue({ items: [] });
        window.history.pushState({}, "", "/calls?agency_id=alpha");
        render(routed(<Calls />));
        await waitFor(() => expect(request).toHaveBeenCalledWith("calls?agency_id=alpha&limit=50"));
    });
});
