import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { request } from "../../api/client";
import { errorText } from "../agencies/AgencyForm";

type Feed = {
    id: string;
    name: string;
    mqtt_target_id?: string | null;
    host?: string | null;
    port: number;
    tls: boolean;
    username?: string | null;
    password?: string | null;
    base_topic: string;
    window_before_s: number;
    window_after_s: number;
    enabled: boolean;
};
type Health = {
    id: string;
    connected: boolean;
    availability?: string | null;
    last_message_at?: string | null;
    invalid_total: number;
    active_incidents: number;
};
const blank: Feed = {
    id: "",
    name: "",
    host: "",
    port: 1883,
    tls: false,
    username: "",
    password: "",
    base_topic: "911/cad",
    window_before_s: 180,
    window_after_s: 300,
    enabled: true,
};

export function CadFeeds() {
    const [items, setItems] = useState<Feed[]>([]);
    const [health, setHealth] = useState<Health[]>([]);
    const [editing, setEditing] = useState<Feed | null>(null);
    const [error, setError] = useState("");
    const reload = () => {
        void request<Feed[]>("cad-feeds")
            .then(setItems)
            .catch(() => undefined);
        void request<{ cad_feeds: Health[] }>("admin/health")
            .then((v) => setHealth(v.cad_feeds ?? []))
            .catch(() => undefined);
    };
    useEffect(reload, []);
    async function save(event: FormEvent) {
        event.preventDefault();
        if (!editing) return;
        setError("");
        if (Boolean(editing.host) === Boolean(editing.mqtt_target_id)) {
            setError("Enter either a host or an MQTT target reference.");
            return;
        }
        const payload: Record<string, unknown> = { ...editing };
        if (editing.password === "" || editing.password === "[REDACTED]") delete payload.password;
        if (!editing.host) delete payload.host;
        if (!editing.mqtt_target_id) delete payload.mqtt_target_id;
        try {
            await request(
                editing.id && items.some((x) => x.id === editing.id)
                    ? `cad-feeds/${editing.id}`
                    : "cad-feeds",
                {
                    method: editing.id && items.some((x) => x.id === editing.id) ? "PUT" : "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                },
            );
            setEditing(null);
            reload();
        } catch (reason) {
            setError(errorText(reason));
        }
    }
    async function remove(id: string) {
        await request(`cad-feeds/${id}`, { method: "DELETE" });
        reload();
    }
    return (
        <>
            <h1>CAD feeds</h1>
            <button onClick={() => setEditing({ ...blank, id: `cad-${Date.now()}` })}>
                Add feed
            </button>
            {items.map((item) => {
                const status = health.find((x) => x.id === item.id);
                return (
                    <section className="card" key={item.id}>
                        <h2>{item.name}</h2>
                        <p>
                            {status?.connected ? "Connected" : "Disconnected"} ·{" "}
                            {status?.availability ?? "unknown"}
                        </p>
                        <p>
                            Last message: {status?.last_message_at ?? "Never"} · Invalid:{" "}
                            {status?.invalid_total ?? 0} · Active: {status?.active_incidents ?? 0}
                        </p>
                        <button onClick={() => setEditing({ ...item, password: "" })}>Edit</button>{" "}
                        <button className="danger" onClick={() => void remove(item.id)}>
                            Delete
                        </button>
                    </section>
                );
            })}
            {editing && (
                <form className="form card" onSubmit={(event) => void save(event)}>
                    <h2>{items.some((x) => x.id === editing.id) ? "Edit" : "Add"} CAD feed</h2>
                    {(
                        [
                            "id",
                            "name",
                            "mqtt_target_id",
                            "host",
                            "username",
                            "password",
                            "base_topic",
                        ] as const
                    ).map((field) => (
                        <label key={field} htmlFor={`cad-${field}`}>
                            {field}
                            <input
                                id={`cad-${field}`}
                                type={field === "password" ? "password" : "text"}
                                value={String(editing[field] ?? "")}
                                onChange={(e) =>
                                    setEditing({ ...editing, [field]: e.target.value || null })
                                }
                            />
                        </label>
                    ))}
                    <label htmlFor="cad-port">
                        Port
                        <input
                            id="cad-port"
                            type="number"
                            value={editing.port}
                            onChange={(e) =>
                                setEditing({ ...editing, port: Number(e.target.value) })
                            }
                        />
                    </label>
                    <label>
                        <input
                            type="checkbox"
                            checked={editing.tls}
                            onChange={(e) => setEditing({ ...editing, tls: e.target.checked })}
                        />{" "}
                        TLS
                    </label>
                    <label htmlFor="cad-before">
                        Window before seconds
                        <input
                            id="cad-before"
                            type="number"
                            value={editing.window_before_s}
                            onChange={(e) =>
                                setEditing({ ...editing, window_before_s: Number(e.target.value) })
                            }
                        />
                    </label>
                    <label htmlFor="cad-after">
                        Window after seconds
                        <input
                            id="cad-after"
                            type="number"
                            value={editing.window_after_s}
                            onChange={(e) =>
                                setEditing({ ...editing, window_after_s: Number(e.target.value) })
                            }
                        />
                    </label>
                    <label>
                        <input
                            type="checkbox"
                            checked={editing.enabled}
                            onChange={(e) => setEditing({ ...editing, enabled: e.target.checked })}
                        />{" "}
                        Enabled
                    </label>
                    <button>Save</button>
                    <button type="button" onClick={() => setEditing(null)}>
                        Cancel
                    </button>
                    {editing.host && editing.mqtt_target_id ? (
                        <p role="alert">Use either a host or an MQTT target reference, not both.</p>
                    ) : null}
                    {!editing.host && !editing.mqtt_target_id ? (
                        <p role="alert">Enter a host or an MQTT target reference.</p>
                    ) : null}
                    {error && <p role="alert">{error}</p>}
                </form>
            )}
        </>
    );
}

export function UnmatchedCadAgencies() {
    const [items, setItems] = useState<
        { key: string; name: string; count: number; last_seen?: string }[]
    >([]);
    const navigate = useNavigate();
    useEffect(() => {
        void request<typeof items>("cad/unmatched-agencies")
            .then(setItems)
            .catch(() => undefined);
    }, []);
    return (
        <>
            <h1>Unmatched CAD agencies</h1>
            {items.length ? (
                <table>
                    <tbody>
                        {items.map((item) => (
                            <tr key={item.key}>
                                <th>{item.name}</th>
                                <td>{item.count}</td>
                                <td>{item.last_seen ?? "Never"}</td>
                                <td>
                                    <button
                                        onClick={() =>
                                            void request<{ id: string }>(
                                                `cad/unmatched-agencies/${encodeURIComponent(item.key)}/create-agency`,
                                                { method: "POST" },
                                            ).then((agency) =>
                                                navigate(`/agencies/${agency.id}/edit`),
                                            )
                                        }
                                    >
                                        Create agency
                                    </button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            ) : (
                <p>No unmatched CAD agencies.</p>
            )}
        </>
    );
}
