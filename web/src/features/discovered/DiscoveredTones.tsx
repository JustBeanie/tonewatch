import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { request } from "../../api/client";
import { useWsEvents } from "../../lib/ws";

type DiscoveredTone = {
    id: number;
    frequencies: number[];
    durations: number[];
    count: number;
    last_seen: string;
    source_ids: string[];
    status: "new" | "dismissed" | "promoted";
    best_clip_recording_path?: string | null;
};

export function relativeTime(value: string): string {
    const seconds = Math.round((Date.now() - Date.parse(value)) / 1000);
    const absolute = Math.abs(seconds);
    if (absolute < 60) return seconds >= 0 ? `${absolute}s ago` : `in ${absolute}s`;
    const minutes = Math.round(absolute / 60);
    if (minutes < 60) return seconds >= 0 ? `${minutes}m ago` : `in ${minutes}m`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return seconds >= 0 ? `${hours}h ago` : `in ${hours}h`;
    const days = Math.round(hours / 24);
    return seconds >= 0 ? `${days}d ago` : `in ${days}d`;
}

export function DiscoveredTones() {
    const [items, setItems] = useState<DiscoveredTone[]>([]);
    const [status, setStatus] = useState("");
    const [source, setSource] = useState("");
    const nav = useNavigate();
    const reload = () => {
        const query = new URLSearchParams();
        if (status) query.set("status", status);
        if (source) query.set("source", source);
        return request<{ items: DiscoveredTone[] }>(`discovered-tones?${query}`)
            .then((data) => setItems(data.items))
            .catch(() => undefined);
    };
    useEffect(() => void reload(), [status, source]);
    useWsEvents("events", (message) => {
        if (message.type === "tone_discovered") void reload();
    });
    async function dismiss(id: number) {
        if (!window.confirm("Dismiss this discovered tone?")) return;
        await request(`discovered-tones/${id}/dismiss`, { method: "POST" });
        void reload();
    }
    async function promote(id: number) {
        const draft = await request<Record<string, unknown>>(`discovered-tones/${id}/promote`, {
            method: "POST",
        });
        nav("/tonesets/new", { state: { draft, discoveredToneId: id } });
    }
    return (
        <>
            <h1>Discovered tones</h1>
            <label htmlFor="discovery-status">
                Status
                <select
                    id="discovery-status"
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                >
                    <option value="">All</option>
                    <option value="new">New</option>
                    <option value="dismissed">Dismissed</option>
                    <option value="promoted">Promoted</option>
                </select>
            </label>
            <label htmlFor="discovery-source">
                Source
                <input
                    id="discovery-source"
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                />
            </label>
            <table>
                <caption>Unmatched tone sequences</caption>
                <thead>
                    <tr>
                        <th scope="col">Tones (Hz)</th>
                        <th scope="col">Durations</th>
                        <th scope="col">Times heard</th>
                        <th scope="col">Last heard</th>
                        <th scope="col">Source</th>
                        <th scope="col">Evidence</th>
                        <th scope="col">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {items.map((item) => (
                        <tr key={item.id}>
                            <td>{item.frequencies.map((value) => value.toFixed(1)).join(" / ")}</td>
                            <td>
                                {item.durations.map((value) => `${value.toFixed(2)}s`).join(" / ")}
                            </td>
                            <td>{item.count}</td>
                            <td>
                                <span>{relativeTime(item.last_seen)}</span>
                                <time dateTime={item.last_seen} title={item.last_seen}>
                                    {new Date(item.last_seen).toLocaleString()}
                                </time>
                            </td>
                            <td>{item.source_ids.join(", ")}</td>
                            <td>
                                {item.best_clip_recording_path ? (
                                    <audio controls src={`/api/discovered-tones/${item.id}/clip`} />
                                ) : (
                                    "—"
                                )}
                            </td>
                            <td>
                                {item.status === "new" && (
                                    <button onClick={() => void promote(item.id)}>
                                        Create tone set
                                    </button>
                                )}
                                {item.status === "new" && (
                                    <button onClick={() => void dismiss(item.id)}>Dismiss</button>
                                )}
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </>
    );
}
