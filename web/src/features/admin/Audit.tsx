import { Fragment, useEffect, useState } from "react";
import { request } from "../../api/client";
import { display, errorText } from "./shared";
type Row = {
    id: number;
    created_at: string;
    actor: string;
    event_type: string;
    resource: string;
    before?: Record<string, unknown> | null;
    after?: Record<string, unknown> | null;
    details?: unknown;
};
type Result = { items: Row[]; next_cursor: string | null };
export function diff(
    before: Record<string, unknown> | null | undefined,
    after: Record<string, unknown> | null | undefined,
) {
    const paths = new Set<string>();
    function visit(left: unknown, right: unknown, path: string) {
        if (JSON.stringify(left) === JSON.stringify(right)) return;
        if (
            left &&
            right &&
            typeof left === "object" &&
            typeof right === "object" &&
            !Array.isArray(left) &&
            !Array.isArray(right)
        ) {
            const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
            for (const key of keys)
                visit(
                    (left as Record<string, unknown>)[key],
                    (right as Record<string, unknown>)[key],
                    path ? `${path}.${key}` : key,
                );
            return;
        }
        paths.add(path);
    }
    visit(before ?? {}, after ?? {}, "");
    return [...paths];
}
export function valueAt(value: Record<string, unknown> | null | undefined, path: string): unknown {
    return path
        .split(".")
        .reduce<unknown>(
            (current, key) =>
                current && typeof current === "object"
                    ? (current as Record<string, unknown>)[key]
                    : undefined,
            value,
        );
}
export function DiffView({
    rows,
}: {
    rows: { path: string; before?: unknown; after?: unknown }[];
}) {
    return (
        <div>
            {rows.map((row) => (
                <p key={row.path}>
                    <code>{row.path}</code>: {String(row.before ?? "—")} →{" "}
                    {String(row.after ?? "—")}
                </p>
            ))}
        </div>
    );
}
export function Audit() {
    const [rows, setRows] = useState<Row[]>([]);
    const [cursor, setCursor] = useState<string | null>(null);
    const [open, setOpen] = useState<number | null>(null);
    const [filters, setFilters] = useState(() => new URLSearchParams(window.location.search));
    const [error, setError] = useState("");
    function update(key: string, value: string) {
        const next = new URLSearchParams(filters);
        const serialized =
            value && (key === "since" || key === "until") ? new Date(value).toISOString() : value;
        if (serialized) next.set(key, serialized);
        else next.delete(key);
        setFilters(next);
        window.history.replaceState(
            {},
            "",
            `${window.location.pathname}${next.toString() ? `?${next}` : ""}`,
        );
    }
    function load(next?: string) {
        const query = new URLSearchParams(filters);
        query.set("limit", "50");
        if (next) query.set("before_id", next);
        void request<Result>(`audit?${query}`)
            .then((result) => {
                setRows((current) =>
                    next
                        ? [
                              ...current,
                              ...result.items.filter(
                                  (row) => !current.some((old) => old.id === row.id),
                              ),
                          ]
                        : result.items,
                );
                setCursor(result.next_cursor);
            })
            .catch((reason: unknown) => setError(errorText(reason)));
    }
    useEffect(() => {
        load();
    }, [filters]);
    return (
        <>
            <h1>Audit log</h1>
            <section className="card">
                <div className="grid">
                    <label>
                        Actor
                        <input
                            value={filters.get("actor") ?? ""}
                            onChange={(e) => update("actor", e.target.value)}
                        />
                    </label>
                    <label>
                        Event type
                        <input
                            value={filters.get("event_type") ?? ""}
                            onChange={(e) => update("event_type", e.target.value)}
                        />
                    </label>
                    <label>
                        Resource
                        <input
                            value={filters.get("resource") ?? ""}
                            onChange={(e) => update("resource", e.target.value)}
                        />
                    </label>
                    <label>
                        Since
                        <input
                            type="datetime-local"
                            value={
                                filters.get("since")
                                    ? new Date(filters.get("since")!).toISOString().slice(0, 16)
                                    : ""
                            }
                            onChange={(e) => update("since", e.target.value)}
                        />
                    </label>
                    <label>
                        Until
                        <input
                            type="datetime-local"
                            value={
                                filters.get("until")
                                    ? new Date(filters.get("until")!).toISOString().slice(0, 16)
                                    : ""
                            }
                            onChange={(e) => update("until", e.target.value)}
                        />
                    </label>
                </div>
            </section>
            {error && <p role="alert">{error}</p>}
            <section className="card">
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Actor</th>
                            <th>Event type</th>
                            <th>Resource</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row) => (
                            <Fragment key={row.id}>
                                <tr
                                    key={row.id}
                                    onClick={() => setOpen(open === row.id ? null : row.id)}
                                >
                                    <td>{display(row.created_at)}</td>
                                    <td>{row.actor}</td>
                                    <td>{row.event_type}</td>
                                    <td>{row.resource}</td>
                                </tr>
                                {open === row.id && (
                                    <tr key={`${row.id}-details`}>
                                        <td colSpan={4}>
                                            <pre>{JSON.stringify(row.details, null, 2)}</pre>
                                            {row.event_type === "config_change" && (
                                                <div>
                                                    <h3>Before / after</h3>
                                                    {diff(row.before, row.after).map((key) => (
                                                        <p key={key}>
                                                            <code>{key}</code>:{" "}
                                                            {String(
                                                                valueAt(row.before, key) ?? "—",
                                                            )}{" "}
                                                            →{" "}
                                                            {String(valueAt(row.after, key) ?? "—")}
                                                        </p>
                                                    ))}
                                                </div>
                                            )}
                                        </td>
                                    </tr>
                                )}
                            </Fragment>
                        ))}
                    </tbody>
                </table>
                {rows.length === 0 && <p>No audit events.</p>}
                {cursor && <button onClick={() => load(cursor)}>Load more</button>}
            </section>
        </>
    );
}
