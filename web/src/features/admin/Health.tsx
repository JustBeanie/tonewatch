import { useCallback, useEffect, useState } from "react";
import { request } from "../../api/client";
import { display, formatBytes, formatDuration, formatFactor, formatForecast } from "./shared";

type HealthData = {
    generated_at: string;
    sources: Array<{
        id: string;
        name: string;
        type: string;
        realtime_factor: number | null;
        dropped_frames: number | null;
        late_frames: number | null;
        restarts: number | null;
        last_restart_at: string | null;
        last_error: string | null;
        feed_health_history: Array<{ healthy?: boolean; reason?: string | null; at?: string }>;
        level: Record<string, unknown> | null;
        squelch_open: boolean | null;
    }>;
    service: {
        subscribers: Array<{ id: string; depth: number; dropped: number; lag_s: number | null }>;
    };
    storage: {
        recordings_bytes?: number;
        free_bytes?: number;
        total_bytes?: number;
        used_bytes?: number;
        db_bytes?: number;
        db_wal_bytes?: number;
        retention_forecast: { days_until_full: number | null };
    };
    outputs: Array<{
        id: string;
        name: string;
        type: string;
        last_success_at: string | null;
        last_error_at: string | null;
        last_error: string | null;
        consecutive_failures: number;
        connection: boolean | string | null;
    }>;
    cad_feeds: Array<{
        id: string;
        name: string;
        connected: boolean;
        availability: string | null;
        last_message_at: string | null;
        invalid_total: number;
        active_incidents: number;
    }>;
    build: { version: string; build: string | null; uptime_s: number };
};

function historySummary(history: HealthData["sources"][number]["feed_health_history"]): string {
    if (!history.length) return "no history";
    const healthy = history.filter((entry) => entry.healthy).length;
    return `${healthy} healthy, ${history.length - healthy} unhealthy`;
}

function connectionText(output: HealthData["outputs"][number]): string {
    if (output.connection === null || output.connection === undefined) return "—";
    if (typeof output.connection === "boolean")
        return `MQTT ${output.connection ? "connected" : "disconnected"}`;
    return output.connection;
}

export function Health() {
    const [health, setHealth] = useState<HealthData>();
    const [error, setError] = useState("");
    const load = useCallback(() => {
        if (document.hidden) return;
        void request<HealthData>("admin/health")
            .then(setHealth)
            .catch((reason: unknown) =>
                setError(reason instanceof Error ? reason.message : "Unable to load health"),
            );
    }, []);
    useEffect(() => {
        load();
        const timer = window.setInterval(load, 10000);
        const onVisibility = () => {
            if (!document.hidden) load();
        };
        document.addEventListener("visibilitychange", onVisibility);
        return () => {
            window.clearInterval(timer);
            document.removeEventListener("visibilitychange", onVisibility);
        };
    }, [load]);
    return (
        <>
            <h1>System health</h1>
            {error && <p role="alert">{error}</p>}
            <section className="card">
                <h2>Sources</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Source</th>
                            <th>Realtime factor</th>
                            <th>Dropped frames</th>
                            <th>Late frames</th>
                            <th>Restarts</th>
                            <th>Last error</th>
                            <th>Squelch</th>
                            <th>Feed history</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(health?.sources ?? []).map((source) => (
                            <tr key={source.id} data-testid={`health-source-${source.id}`}>
                                <th scope="row">{source.name}</th>
                                <td>
                                    {formatFactor(source.realtime_factor)}{" "}
                                    {source.realtime_factor !== null &&
                                        source.realtime_factor < 1.5 && (
                                            <strong role="alert">Warning: below 1.5×</strong>
                                        )}
                                </td>
                                <td>{display(source.dropped_frames)}</td>
                                <td>{display(source.late_frames)}</td>
                                <td>{display(source.restarts)}</td>
                                <td>{display(source.last_error)}</td>
                                <td>{display(source.squelch_open)}</td>
                                <td>
                                    <span aria-label={historySummary(source.feed_health_history)}>
                                        {source.feed_health_history.length
                                            ? source.feed_health_history.map((entry, index) => (
                                                  <span
                                                      key={`${source.id}-${index}`}
                                                      aria-label={
                                                          entry.healthy ? "healthy" : "unhealthy"
                                                      }
                                                  >
                                                      {entry.healthy ? "●" : "○"}
                                                  </span>
                                              ))
                                            : "no history"}
                                    </span>
                                    <span className="visually-hidden">
                                        {" "}
                                        {historySummary(source.feed_health_history)}
                                    </span>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {health?.sources.length === 0 && <p>No sources.</p>}
            </section>
            <section className="card">
                <h2>Event bus</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Subscriber</th>
                            <th>Depth</th>
                            <th>Dropped</th>
                            <th>Lag</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(health?.service.subscribers ?? []).map((subscriber) => (
                            <tr key={subscriber.id}>
                                <th scope="row">{subscriber.id}</th>
                                <td>{display(subscriber.depth)}</td>
                                <td>{display(subscriber.dropped)}</td>
                                <td>
                                    {subscriber.lag_s === null
                                        ? "—"
                                        : `${subscriber.lag_s.toFixed(1)}s`}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <p>
                    Total subscribers: {health?.service.subscribers.length ?? 0} · Total dropped:{" "}
                    {(health?.service.subscribers ?? []).reduce(
                        (sum, item) => sum + item.dropped,
                        0,
                    )}
                </p>
            </section>
            <section className="card">
                <h2>Storage</h2>
                <dl className="health-definitions">
                    <div>
                        <dt>Used</dt>
                        <dd>{formatBytes(health?.storage.used_bytes)}</dd>
                    </div>
                    <div>
                        <dt>Free</dt>
                        <dd>{formatBytes(health?.storage.free_bytes)}</dd>
                    </div>
                    <div>
                        <dt>Recordings</dt>
                        <dd>{formatBytes(health?.storage.recordings_bytes)}</dd>
                    </div>
                    <div>
                        <dt>Database</dt>
                        <dd>{formatBytes(health?.storage.db_bytes)}</dd>
                    </div>
                    <div>
                        <dt>Forecast</dt>
                        <dd>
                            {formatForecast(health?.storage.retention_forecast.days_until_full)}
                        </dd>
                    </div>
                </dl>
            </section>
            <section className="card">
                <h2>Outputs</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Target</th>
                            <th>Last success</th>
                            <th>Last error</th>
                            <th>Consecutive failures</th>
                            <th>Connection</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(health?.outputs ?? []).map((output) => (
                            <tr key={output.id}>
                                <th scope="row">{output.name}</th>
                                <td>{display(output.last_success_at)}</td>
                                <td>{display(output.last_error)}</td>
                                <td>{display(output.consecutive_failures)}</td>
                                <td>{connectionText(output)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>
            <section className="card">
                <h2>CAD feeds</h2>
                <table>
                    <thead>
                        <tr>
                            <th>Feed</th>
                            <th>Connected</th>
                            <th>Availability</th>
                            <th>Last message</th>
                            <th>Invalid</th>
                            <th>Active incidents</th>
                        </tr>
                    </thead>
                    <tbody>
                        {(health?.cad_feeds ?? []).map((feed) => (
                            <tr key={feed.id}>
                                <th scope="row">{feed.name}</th>
                                <td>{display(feed.connected)}</td>
                                <td>{display(feed.availability)}</td>
                                <td>{display(feed.last_message_at)}</td>
                                <td>{display(feed.invalid_total)}</td>
                                <td>{display(feed.active_incidents)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </section>
            <section className="card">
                <h2>Build</h2>
                <dl className="health-definitions">
                    <div>
                        <dt>Version</dt>
                        <dd>{display(health?.build.version)}</dd>
                    </div>
                    <div>
                        <dt>Build</dt>
                        <dd>{display(health?.build.build)}</dd>
                    </div>
                    <div>
                        <dt>Uptime</dt>
                        <dd>{formatDuration(health?.build.uptime_s)}</dd>
                    </div>
                </dl>
            </section>
        </>
    );
}
