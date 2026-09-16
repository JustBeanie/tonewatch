import { useEffect, useState } from "react";
import { request } from "../../api/client";
export function Settings() {
    const [auth, setAuth] = useState<{ authenticated: boolean; password_required: boolean }>();
    const [ready, setReady] = useState<boolean>();
    const [config, setConfig] = useState<{
        live_stream?: { enabled?: boolean };
        [key: string]: unknown;
    }>();
    const [saved, setSaved] = useState("");
    useEffect(() => {
        request<typeof auth>("auth/status")
            .then(setAuth)
            .catch(() => undefined);
        fetch("/readyz")
            .then((r) => setReady(r.ok))
            .catch(() => undefined);
        request<typeof config>("config")
            .then(setConfig)
            .catch(() => undefined);
    }, []);
    async function saveLiveStream(enabled: boolean) {
        if (!config) return;
        const next = { ...config, live_stream: { ...(config.live_stream ?? {}), enabled } };
        setConfig(next);
        try {
            await request("config", {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(next),
            });
            setSaved("Live streaming setting saved.");
        } catch {
            setSaved("Unable to save live streaming setting.");
        }
    }
    return (
        <>
            <h1>Settings</h1>
            <section className="card">
                <h2>API status</h2>
                <p>Authenticated: {auth?.authenticated ? "yes" : "no"}</p>
                <p>Ready: {ready === undefined ? "checking…" : ready ? "yes" : "no"}</p>
            </section>
            <section className="card">
                <h2>Live rebroadcast</h2>
                <label htmlFor="live-stream-enabled">
                    <input
                        id="live-stream-enabled"
                        type="checkbox"
                        checked={config?.live_stream?.enabled ?? false}
                        onChange={(event) => void saveLiveStream(event.target.checked)}
                        disabled={!config}
                    />
                    Enable live streaming
                </label>
                <p>
                    Radio rebroadcasting may be regulated by local, state, or national law and by
                    the terms of the source service. You are responsible for obtaining permission
                    and complying with applicable privacy, copyright, emergency-communications, and
                    rebroadcast rules.
                </p>
                {saved && <p role="status">{saved}</p>}
            </section>
            <p>
                Retention, MQTT, input devices, and other deployment settings are configured in
                config.yaml / add-on options.
            </p>
        </>
    );
}
