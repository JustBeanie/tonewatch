import { useEffect, useState } from "react";
import { apiUrl } from "../../lib/urls";
import { csrfToken, errorText } from "./shared";

type Config = {
    alert_targets?: Array<{ id: string; name: string }>;
    admin_alerts?: Record<string, unknown>;
    [key: string]: unknown;
};
const fields: Array<[string, string, number, number, number | boolean]> = [
    ["feed_unhealthy_min", "Dead feed minutes", 1, 1440, 5],
    ["disk_used_pct", "Disk used percent", 50, 99, 90],
    ["disk_forecast_days", "Disk forecast days", 1, 365, 7],
    ["target_failures", "Target failures", 2, 100, 5],
    ["realtime_factor_min", "Realtime factor minimum", 1, 10, 1.5],
    ["realtime_factor_min_s", "Slow DSP seconds", 30, 3600, 300],
    ["min_interval_s", "Minimum interval seconds", 60, 86400, 300],
    ["max_per_hour", "Maximum alerts per hour", 1, 100, 6],
];

async function configRequest(method: "GET" | "PUT", body?: Config, etag?: string) {
    const headers = new Headers({ "Content-Type": "application/json" });
    if (method === "PUT") {
        const csrf = csrfToken();
        if (csrf) headers.set("X-CSRF-Token", csrf);
        if (etag) headers.set("If-Match", etag);
    }
    const init: RequestInit = { method, headers, credentials: "same-origin" };
    if (body) init.body = JSON.stringify(body);
    const response = await fetch(apiUrl("config"), init);
    const data = await response.json().catch(() => undefined);
    if (!response.ok)
        throw Object.assign(new Error(`Request failed (${response.status})`), {
            status: response.status,
            body: data,
        });
    return { data: data as Config, etag: response.headers.get("ETag") ?? "" };
}

export function AdminAlerts() {
    const [config, setConfig] = useState<Config>();
    const [etag, setEtag] = useState("");
    const [error, setError] = useState("");
    const [saved, setSaved] = useState("");
    useEffect(() => {
        void configRequest("GET")
            .then((result) => {
                setConfig(result.data);
                setEtag(result.etag);
            })
            .catch((reason: unknown) => setError(errorText(reason)));
    }, []);
    const admin = config?.admin_alerts ?? {};
    function update(key: string, next: unknown) {
        setConfig((current) =>
            current
                ? { ...current, admin_alerts: { ...(current.admin_alerts ?? {}), [key]: next } }
                : current,
        );
    }
    async function save() {
        if (!config) return;
        setError("");
        setSaved("");
        try {
            const result = await configRequest("PUT", config, etag);
            setConfig(result.data);
            setEtag(result.etag);
            setSaved("Admin alerts saved.");
        } catch (reason: unknown) {
            setError(
                (reason as { status?: number }).status === 412
                    ? "Configuration changed elsewhere, reload."
                    : errorText(reason),
            );
        }
    }
    return (
        <>
            <h1>Admin alerts</h1>
            <p>
                Admin alerts are separate from pages and are marked <code>admin</code>.
            </p>
            <section className="card">
                <div className="form">
                    <label className="inline-label" htmlFor="admin-alert-enabled">
                        <input
                            id="admin-alert-enabled"
                            type="checkbox"
                            checked={Boolean(admin.enabled)}
                            onChange={(event) => update("enabled", event.target.checked)}
                            disabled={!config}
                        />
                        Enable admin alerts
                    </label>
                    <label htmlFor="admin-alert-targets">
                        Alert targets
                        <select
                            id="admin-alert-targets"
                            multiple
                            value={Array.isArray(admin.targets) ? admin.targets.map(String) : []}
                            onChange={(event) =>
                                update(
                                    "targets",
                                    Array.from(
                                        event.target.selectedOptions,
                                        (option) => option.value,
                                    ),
                                )
                            }
                        >
                            {(config?.alert_targets ?? []).map((target) => (
                                <option key={target.id} value={target.id}>
                                    {target.name}
                                </option>
                            ))}
                        </select>
                    </label>
                    {fields.map(([key, label, min, max, fallback]) => (
                        <label key={key} htmlFor={`admin-${key}`}>
                            {label} ({min}–{max})
                            <input
                                id={`admin-${key}`}
                                type="number"
                                min={min}
                                max={max}
                                step={
                                    typeof fallback === "number" && !Number.isInteger(fallback)
                                        ? "0.1"
                                        : "1"
                                }
                                value={String(admin[key] ?? fallback)}
                                onChange={(event) => update(key, Number(event.target.value))}
                            />
                        </label>
                    ))}
                    <button onClick={() => void save()} disabled={!config}>
                        Save
                    </button>
                    {saved && <p role="status">{saved}</p>}
                    {error && <p role="alert">{error}</p>}
                </div>
            </section>
        </>
    );
}
