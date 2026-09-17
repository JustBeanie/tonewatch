import { useEffect, useState } from "react";
import { Link } from "react-router";
import { request } from "../../api/client";
import { useConnectionStatus, useSubscription, useWsEvents, WsMessage } from "../../lib/ws";
import { LivePlayer, Source } from "../sources/SourceControls";
import { ActiveIncidents } from "../cad/Incidents";
type Call = { id: string; started_at: string; source_id: string; status: string };
export function Dashboard() {
    const [event, setEvent] = useState<WsMessage>();
    const [calls, setCalls] = useState<Call[]>([]);
    const [discoveredCount, setDiscoveredCount] = useState(0);
    const [sources, setSources] = useState<Source[]>([]);
    useWsEvents("events", (message) => {
        setEvent(message);
        const d = message.data;
        if (d && ["ToneDetected", "RecordingReady", "CallClosed"].includes(message.type))
            setCalls((o) =>
                [
                    {
                        ...(d as unknown as Call),
                        id: String(d.id ?? d.call_id ?? crypto.randomUUID()),
                    },
                    ...o,
                ].slice(0, 50),
            );
        if (message.type === "tone_discovered") setDiscoveredCount((count) => count + 1);
    });
    const level = useSubscription("levels");
    const connection = useConnectionStatus();
    useEffect(() => {
        request<{ items?: Call[] }>("calls?limit=50")
            .then((v) => setCalls(v.items ?? []))
            .catch(() => undefined);
        request<{ items?: unknown[] }>("discovered-tones?status=new&limit=500")
            .then((v) => setDiscoveredCount(v.items?.length ?? 0))
            .catch(() => undefined);
        request<Source[]>("sources")
            .then((value) => setSources(Array.isArray(value) ? value : []))
            .catch(() => undefined);
    }, []);
    const db = Number(level?.data?.dbfs ?? -100);
    return (
        <>
            <h1>Dashboard</h1>
            <Link to="/discovered-tones" aria-label={`${discoveredCount} new discovered tones`}>
                {discoveredCount} new discovered tones
            </Link>
            <p role="status" aria-label="Live connection">
                Live connection: {connection}
            </p>
            {event?.type === "FeedHealthChanged" && (
                <p role="status">Feed health: {String(event.data?.reason ?? "")}</p>
            )}
            <section className="grid">
                <ActiveIncidents />
                {sources.map((source) => (
                    <div className="card" key={source.id}>
                        <h2>{source.name ?? source.id}</h2>
                        <LivePlayer source={source} message={event} />
                    </div>
                ))}
                <div className="card">
                    <h2>Channel levels</h2>
                    <div
                        role="meter"
                        aria-label="Audio level"
                        aria-valuemin={-100}
                        aria-valuemax={0}
                        aria-valuenow={db}
                    >
                        {db.toFixed(1)} dBFS
                    </div>
                </div>
                <div className="card">
                    <h2>Live calls</h2>
                    {calls.length ? (
                        calls.map((c) => (
                            <Link key={c.id} to={`/calls/${c.id}`}>
                                <p>
                                    {c.source_id} · {c.status} · {c.started_at}
                                </p>
                            </Link>
                        ))
                    ) : (
                        <p>
                            No calls yet. <Link to="/sources">Configure a source</Link>.
                        </p>
                    )}
                </div>
            </section>
        </>
    );
}
