import { useEffect, useState } from "react";
import { Link } from "react-router";
import { request } from "../../api/client";
import { useWsEvents, WsMessage } from "../../lib/ws";

export type Incident = {
    feed_id: string;
    incident_id: string;
    agency_name?: string;
    agency_key?: string;
    type?: { raw?: string; code?: string | null };
    address_clean?: string;
    cross_streets?: string[];
    municipality?: string | { name?: string | null };
    received_at?: string;
    feed_name?: string;
    call_id?: string | null;
    delta_s?: number;
};
const EMPTY_INCIDENTS: Incident[] = [];

function localTime(value?: string): string {
    return value ? new Date(value).toLocaleString() : "Unknown";
}

function delta(value: number | undefined): string {
    if (value === undefined) return "";
    return `${value >= 0 ? "+" : ""}${value.toFixed(1)}s from call start`;
}

export function IncidentCard({ incident, callStart }: { incident: Incident; callStart?: string }) {
    const received = incident.received_at ? new Date(incident.received_at).getTime() : undefined;
    const started = callStart ? new Date(callStart).getTime() : undefined;
    const difference =
        incident.delta_s ??
        (received !== undefined && started !== undefined ? (received - started) / 1000 : undefined);
    const municipality =
        typeof incident.municipality === "string"
            ? incident.municipality
            : incident.municipality?.name;
    return (
        <article className="card" aria-label="CAD incident">
            <h3>
                {incident.type?.raw || "CAD incident"}
                {incident.type?.code ? ` (${incident.type.code})` : ""}
            </h3>
            <p>{incident.address_clean || "Address unavailable"}</p>
            {incident.cross_streets?.length ? (
                <p>Cross streets: {incident.cross_streets.join(" / ")}</p>
            ) : null}
            <p>{municipality || "Municipality unavailable"}</p>
            <p>
                Received: {localTime(incident.received_at)} {delta(difference)}
            </p>
            <p>Feed: {incident.feed_name || incident.feed_id}</p>
            {incident.call_id ? <Link to={`/calls/${incident.call_id}`}>Open call</Link> : null}
        </article>
    );
}

export function useCallIncidents(
    callId: string | undefined,
    initial: Incident[] = EMPTY_INCIDENTS,
) {
    const [items, setItems] = useState(initial);
    useEffect(() => setItems(initial), [initial.length]);
    useWsEvents("events", (message: WsMessage) => {
        if (message.type !== "call_enriched" || String(message.data?.call_id) !== callId) return;
        const data = message.data?.incident;
        if (data && typeof data === "object") setItems((old) => [...old, data as Incident]);
    });
    return items;
}

export function ActiveIncidents() {
    const [items, setItems] = useState<Incident[]>([]);
    const [feeds, setFeeds] = useState<{ id: string }[]>([]);
    const load = () =>
        request<Incident[]>("cad/incidents?status=active&configured_only=true&limit=10")
            .then(setItems)
            .catch(() => undefined);
    useEffect(() => {
        request<{ id: string }[]>("cad-feeds")
            .then((value) => {
                setFeeds(value);
                if (value.length) void load();
            })
            .catch(() => undefined);
    }, []);
    if (!feeds.length) return null;
    return (
        <section className="card" aria-label="Active CAD incidents">
            <h2>Active CAD incidents</h2>
            {items.length ? (
                items
                    .slice(0, 10)
                    .map((item) => (
                        <IncidentCard key={`${item.feed_id}-${item.incident_id}`} incident={item} />
                    ))
            ) : (
                <p>No active incidents.</p>
            )}
        </section>
    );
}

export function RecentIncidents({ agencyNames }: { agencyNames: string[] }) {
    const [items, setItems] = useState<Incident[]>([]);
    useEffect(() => {
        request<Incident[]>("cad/incidents?status=active&configured_only=false&limit=100")
            .then((value) =>
                setItems(
                    value.filter((item) =>
                        agencyNames.some(
                            (name) => name.toLowerCase() === item.agency_key?.toLowerCase(),
                        ),
                    ),
                ),
            )
            .catch(() => undefined);
    }, [agencyNames]);
    return (
        <>
            {items.slice(0, 5).map((item) => (
                <IncidentCard key={`${item.feed_id}-${item.incident_id}`} incident={item} />
            ))}
        </>
    );
}
