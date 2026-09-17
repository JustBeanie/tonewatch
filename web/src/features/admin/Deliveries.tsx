import { useEffect, useState } from "react";
import { request } from "../../api/client";
import { display, errorText } from "./shared";

type Attempt = {
    id: number;
    call_id: string;
    target_id: string;
    phase: string;
    ok: boolean;
    status_code?: number | null;
    error?: string | null;
    created_at: string;
    retry: boolean;
};
type Result = { items: Attempt[]; next_cursor: string | null };
function paramsFromUrl() {
    return new URLSearchParams(window.location.search);
}

export function Deliveries() {
    const [items, setItems] = useState<Attempt[]>([]);
    const [cursor, setCursor] = useState<string | null>(null);
    const [filters, setFilters] = useState(() => paramsFromUrl());
    const [message, setMessage] = useState("");
    const [loading, setLoading] = useState(false);
    const load = (next?: string | null) => {
        setLoading(true);
        const query = new URLSearchParams(filters);
        if (next) query.set("cursor", next);
        void request<Result>(`admin/alert-attempts?${query.toString()}`)
            .then((result) => {
                setItems((current) =>
                    next
                        ? [
                              ...current,
                              ...result.items.filter(
                                  (item) => !current.some((old) => old.id === item.id),
                              ),
                          ]
                        : result.items,
                );
                setCursor(result.next_cursor);
            })
            .catch((reason: unknown) => setMessage(errorText(reason)))
            .finally(() => setLoading(false));
    };
    useEffect(() => {
        load();
    }, [filters]);
    function filter(key: string, value: string) {
        const next = new URLSearchParams(filters);
        if (value) next.set(key, value);
        else next.delete(key);
        setFilters(next);
        window.history.replaceState({}, "", `${window.location.pathname}?${next.toString()}`);
    }
    async function retry(item: Attempt) {
        if (!window.confirm("Retry this failed delivery?")) return;
        try {
            const result = await request<{ ok: boolean; error?: string }>(
                `admin/alert-attempts/${item.id}/retry`,
                { method: "POST" },
            );
            setMessage(
                result.ok
                    ? "Retry succeeded"
                    : result.error === "rate_limited"
                      ? "Rate limited"
                      : display(result.error),
            );
            load();
        } catch (reason: unknown) {
            const status = (reason as { status?: number }).status;
            if (status === 429) setMessage("A retry is already running");
            else if (status === 409) {
                const detail = String(
                    (reason as { body?: { detail?: string } }).body?.detail ?? "",
                );
                setMessage(
                    detail.includes("succeeded")
                        ? "Already succeeded"
                        : "Call or target no longer exists",
                );
            } else setMessage(errorText(reason));
        }
    }
    return (
        <>
            <h1>Delivery log</h1>
            <section className="card">
                <div className="grid">
                    <label htmlFor="delivery-call">
                        Call ID
                        <input
                            id="delivery-call"
                            value={filters.get("call_id") ?? ""}
                            onChange={(event) => filter("call_id", event.target.value)}
                        />
                    </label>
                    <label htmlFor="delivery-target">
                        Target ID
                        <input
                            id="delivery-target"
                            value={filters.get("target_id") ?? ""}
                            onChange={(event) => filter("target_id", event.target.value)}
                        />
                    </label>
                    <label htmlFor="delivery-phase">
                        Phase
                        <select
                            id="delivery-phase"
                            value={filters.get("phase") ?? ""}
                            onChange={(event) => filter("phase", event.target.value)}
                        >
                            <option value="">All</option>
                            <option value="pre_alert">Pre-alert</option>
                            <option value="closed">Closed</option>
                        </select>
                    </label>
                    <label htmlFor="delivery-ok">
                        Outcome
                        <select
                            id="delivery-ok"
                            value={filters.get("ok") ?? ""}
                            onChange={(event) => filter("ok", event.target.value)}
                        >
                            <option value="">All</option>
                            <option value="true">Succeeded</option>
                            <option value="false">Failed</option>
                        </select>
                    </label>
                </div>
            </section>
            {message && <p role="status">{message}</p>}
            <section className="card">
                <table>
                    <caption className="visually-hidden">Alert delivery attempts</caption>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Call</th>
                            <th>Target</th>
                            <th>Phase</th>
                            <th>Outcome</th>
                            <th>Status or error</th>
                            <th>Retry</th>
                        </tr>
                    </thead>
                    <tbody>
                        {items.map((item) => (
                            <tr key={item.id}>
                                <td>{display(item.created_at)}</td>
                                <td>
                                    <a href={`/calls/${item.call_id}`}>{item.call_id}</a>
                                </td>
                                <td>{item.target_id}</td>
                                <td>{item.phase}</td>
                                <td>{item.ok ? "Succeeded" : "Failed"}</td>
                                <td>{item.ok ? display(item.status_code) : display(item.error)}</td>
                                <td>
                                    {!item.ok && (
                                        <button onClick={() => void retry(item)}>Retry</button>
                                    )}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {items.length === 0 && !loading && <p>No delivery attempts.</p>}
                {cursor && <button onClick={() => load(cursor)}>Load more</button>}
            </section>
        </>
    );
}
