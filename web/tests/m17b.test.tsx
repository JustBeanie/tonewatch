import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import {
    ActiveIncidents,
    IncidentCard,
    RecentIncidents,
    useCallIncidents,
} from "../src/features/cad/Incidents";
import { CadFeeds, UnmatchedCadAgencies } from "../src/features/cad/CadFeeds";
import { Calls } from "../src/features/calls/Calls";

const request = vi.hoisted(() => vi.fn());
const ws = vi.hoisted(() => ({
    handler: undefined as
        ((message: { type: string; data?: Record<string, unknown> }) => void) | undefined,
}));
vi.mock("../src/api/client", () => ({ request }));
vi.mock("../src/lib/ws", () => ({
    useWsEvents: (_topic: string, handler: typeof ws.handler) => {
        ws.handler = handler;
    },
    useSubscription: () => undefined,
    useConnectionStatus: () => "connected",
}));
function fixture() {
    return {
        feed_id: "feed",
        incident_id: "one",
        agency_name: "North Unit",
        agency_key: "north unit",
        type: { raw: "Medical assist", code: "31A" },
        address_clean: "Fictional Avenue",
        cross_streets: ["Imaginary Road"],
        municipality: "Fictional City",
        received_at: "2026-01-01T00:00:10Z",
        feed_name: "County CAD",
        call_id: "call-1",
    };
}
afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    ws.handler = undefined;
});

describe("M17b CAD UI", () => {
    it("renders the complete incident card", () => {
        render(
            <MemoryRouter>
                <IncidentCard incident={fixture()} callStart="2026-01-01T00:00:00Z" />
            </MemoryRouter>,
        );
        expect(screen.getByText("Medical assist (31A)")).toBeInTheDocument();
        expect(screen.getByText("Fictional Avenue")).toBeInTheDocument();
        expect(screen.getByText(/Imaginary Road/)).toBeInTheDocument();
        expect(screen.getByText("Fictional City")).toBeInTheDocument();
        expect(screen.getByText(/County CAD/)).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Open call" })).toHaveAttribute(
            "href",
            "/calls/call-1",
        );
    });
    it("renders sparse incident data safely", () => {
        render(
            <MemoryRouter>
                <IncidentCard
                    incident={{
                        feed_id: "f",
                        incident_id: "s",
                        municipality: { name: "Town" },
                        type: { raw: "Alarm", code: null },
                        cross_streets: [],
                    }}
                />
            </MemoryRouter>,
        );
        expect(screen.getByText("Town")).toBeInTheDocument();
        expect(screen.getByText(/Address unavailable/)).toBeInTheDocument();
    });
    it("applies same-tick enrichment and another event losslessly", async () => {
        function Probe() {
            const items = useCallIncidents("call-1");
            return <p>{items.map((item) => item.incident_id).join(",")}</p>;
        }
        render(<Probe />);
        ws.handler?.({ type: "call_enriched", data: { call_id: "call-1", incident: fixture() } });
        ws.handler?.({
            type: "call_enriched",
            data: { call_id: "call-1", incident: { ...fixture(), incident_id: "two" } },
        });
        await waitFor(() => expect(screen.getByText("one,two")).toBeInTheDocument());
    });
    it("hides empty cards and gates active panel on feeds", async () => {
        request.mockImplementation((path: string) =>
            Promise.resolve(path === "cad-feeds" ? [] : { cad_feeds: [] }),
        );
        const { container } = render(
            <MemoryRouter>
                <IncidentCard incident={{ feed_id: "f", incident_id: "e" }} />
                <ActiveIncidents />
            </MemoryRouter>,
        );
        expect(container.querySelector("[aria-label='CAD incident'] h3")).toHaveTextContent(
            "CAD incident",
        );
        await waitFor(() =>
            expect(
                screen.queryByRole("heading", { name: "Active CAD incidents" }),
            ).not.toBeInTheDocument(),
        );
    });
    it("renders active incidents newest-first with a maximum of ten", async () => {
        const values = Array.from({ length: 11 }, (_, i) => ({
            ...fixture(),
            incident_id: String(i),
            received_at: `2026-01-01T00:00:${String(59 - i).padStart(2, "0")}Z`,
        }));
        request.mockImplementation((path: string) =>
            Promise.resolve(path === "cad-feeds" ? [{ id: "feed" }] : values),
        );
        render(
            <MemoryRouter>
                <ActiveIncidents />
            </MemoryRouter>,
        );
        await waitFor(() =>
            expect(
                screen.getByRole("heading", { name: "Active CAD incidents" }),
            ).toBeInTheDocument(),
        );
        expect(screen.getAllByRole("article")).toHaveLength(10);
    });
    it("filters recent agency incidents", async () => {
        request.mockResolvedValue([
            { ...fixture() },
            { ...fixture(), incident_id: "other", agency_key: "south" },
        ]);
        render(
            <MemoryRouter>
                <RecentIncidents agencyNames={["North Unit"]} />
            </MemoryRouter>,
        );
        await waitFor(() => expect(screen.getAllByText("Fictional Avenue")).toHaveLength(1));
        expect(screen.getAllByRole("article")).toHaveLength(1);
    });
    it("creates a feed, displays server errors, and omits redacted passwords on edit", async () => {
        request
            .mockResolvedValueOnce([])
            .mockResolvedValueOnce({ cad_feeds: [] })
            .mockRejectedValueOnce(
                Object.assign(new Error("422"), { body: { detail: "invalid feed" } }),
            );
        render(<CadFeeds />);
        fireEvent.click(screen.getByRole("button", { name: "Add feed" }));
        fireEvent.change(screen.getByLabelText("name"), { target: { value: "County" } });
        fireEvent.change(screen.getByLabelText("host"), { target: { value: "127.0.0.1" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("invalid feed"));
        expect(JSON.stringify(request.mock.calls)).not.toContain("[REDACTED]");
    });
    it("creates an unmatched agency and navigates to its editor", async () => {
        request
            .mockResolvedValueOnce([
                { key: "north", name: "North Unit", count: 2, last_seen: "today" },
            ])
            .mockResolvedValueOnce({ id: "north" });
        render(
            <MemoryRouter>
                <UnmatchedCadAgencies />
            </MemoryRouter>,
        );
        fireEvent.click(await screen.findByRole("button", { name: "Create agency" }));
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "cad/unmatched-agencies/north/create-agency",
                expect.objectContaining({ method: "POST" }),
            ),
        );
    });
    it("covers feed edit/delete and unmatched empty states", async () => {
        request.mockImplementation((path: string, init?: RequestInit) => {
            if (path === "cad-feeds" && !init)
                return Promise.resolve([
                    {
                        id: "f",
                        name: "Feed",
                        host: "127.0.0.1",
                        port: 1883,
                        tls: false,
                        base_topic: "cad",
                        window_before_s: 1,
                        window_after_s: 1,
                        enabled: true,
                    },
                ]);
            if (path === "admin/health")
                return Promise.resolve({
                    cad_feeds: [
                        { id: "f", connected: false, invalid_total: 2, active_incidents: 1 },
                    ],
                });
            return Promise.resolve({});
        });
        render(
            <MemoryRouter>
                <CadFeeds />
            </MemoryRouter>,
        );
        fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
        fireEvent.change(screen.getByLabelText("password"), { target: { value: "" } });
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "cad-feeds/f",
                expect.objectContaining({ method: "PUT" }),
            ),
        );
        fireEvent.click(screen.getByRole("button", { name: "Delete" }));
        await waitFor(() =>
            expect(request).toHaveBeenCalledWith(
                "cad-feeds/f",
                expect.objectContaining({ method: "DELETE" }),
            ),
        );
        cleanup();
        request.mockResolvedValue([]);
        render(
            <MemoryRouter>
                <UnmatchedCadAgencies />
            </MemoryRouter>,
        );
        expect(await screen.findByText("No unmatched CAD agencies.")).toBeInTheDocument();
    });
    it("covers feed field controls and broker validation", async () => {
        request.mockResolvedValue([]);
        render(<CadFeeds />);
        fireEvent.click(screen.getByRole("button", { name: "Add feed" }));
        fireEvent.change(screen.getByLabelText("id"), { target: { value: "new-feed" } });
        fireEvent.change(screen.getByLabelText("mqtt_target_id"), { target: { value: "target" } });
        fireEvent.change(screen.getByLabelText("host"), { target: { value: "127.0.0.1" } });
        fireEvent.change(screen.getByLabelText("username"), { target: { value: "user" } });
        fireEvent.change(screen.getByLabelText("base_topic"), { target: { value: "base" } });
        fireEvent.change(screen.getByLabelText("Port"), { target: { value: "1884" } });
        fireEvent.click(screen.getByLabelText("TLS"));
        fireEvent.change(screen.getByLabelText("Window before seconds"), {
            target: { value: "2" },
        });
        fireEvent.change(screen.getByLabelText("Window after seconds"), { target: { value: "3" } });
        fireEvent.click(screen.getByLabelText("Enabled"));
        fireEvent.click(screen.getByRole("button", { name: "Save" }));
        expect(
            screen.getAllByRole("alert").some((item) => item.textContent?.includes("Enter either")),
        ).toBe(true);
        fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
        await waitFor(() =>
            expect(screen.queryByRole("heading", { name: "Add CAD feed" })).not.toBeInTheDocument(),
        );
    });
    it("shows the active incident empty state when a feed is configured", async () => {
        request.mockImplementation((path: string) =>
            Promise.resolve(path === "cad-feeds" ? [{ id: "feed" }] : []),
        );
        render(
            <MemoryRouter>
                <ActiveIncidents />
            </MemoryRouter>,
        );
        expect(await screen.findByText("No active incidents.")).toBeInTheDocument();
    });
    it("handles CAD list failures without exposing incident data", async () => {
        request.mockRejectedValue(new Error("offline"));
        render(
            <MemoryRouter>
                <ActiveIncidents />
                <UnmatchedCadAgencies />
            </MemoryRouter>,
        );
        await waitFor(() =>
            expect(screen.getByText("No unmatched CAD agencies.")).toBeInTheDocument(),
        );
    });
    it("adds the CAD badge from a live enrichment", async () => {
        request.mockResolvedValue({
            items: [
                {
                    id: "call-1",
                    started_at: "now",
                    source_id: "radio",
                    status: "open",
                    has_cad: false,
                },
            ],
        });
        render(
            <MemoryRouter>
                <Calls />
            </MemoryRouter>,
        );
        await screen.findByText(/radio/);
        ws.handler?.({ type: "call_enriched", data: { call_id: "call-1" } });
        expect(await screen.findByLabelText("CAD incident")).toBeInTheDocument();
    });
});
