import { useEffect, useState } from "react";
import { Link } from "react-router";
import { request } from "../../api/client";
import { useConnectionStatus, useSubscription } from "../../lib/ws";
type Call = { id: string; started_at: string; source_id: string; status: string };
export function Dashboard() {
    const event = useSubscription("events"),
        level = useSubscription("levels");
    const connection = useConnectionStatus();
    const [calls, setCalls] = useState<Call[]>([]);
    useEffect(() => {
        request<{ items?: Call[] }>("calls?limit=50")
            .then((v) => setCalls(v.items ?? []))
            .catch(() => undefined);
    }, []);
    useEffect(() => {
        const d = event?.data;
        if (d && ["ToneDetected", "RecordingReady", "CallClosed"].includes(event.type))
            setCalls((o) =>
                [
                    {
                        ...(d as unknown as Call),
                        id: String(d.id ?? d.call_id ?? crypto.randomUUID()),
                    },
                    ...o,
                ].slice(0, 50),
            );
    }, [event]);
    const db = Number(level?.data?.dbfs ?? -100);
    return (
        <>
            <h1>Dashboard</h1>
            <p role="status" aria-label="Live connection">
                Live connection: {connection}
            </p>
            {event?.type === "FeedHealthChanged" && (
                <p role="status">Feed health: {String(event.data?.reason ?? "")}</p>
            )}
            <section className="grid">
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
