import { useEffect, useState } from "react";
import { request } from "../../api/client";
export function Settings() {
    const [auth, setAuth] = useState<{ authenticated: boolean; password_required: boolean }>();
    const [ready, setReady] = useState<boolean>();
    useEffect(() => {
        request<typeof auth>("auth/status")
            .then(setAuth)
            .catch(() => undefined);
        fetch("/readyz")
            .then((r) => setReady(r.ok))
            .catch(() => undefined);
    }, []);
    return (
        <>
            <h1>Settings</h1>
            <section className="card">
                <h2>API status</h2>
                <p>Authenticated: {auth?.authenticated ? "yes" : "no"}</p>
                <p>Ready: {ready === undefined ? "checking…" : ready ? "yes" : "no"}</p>
            </section>
            <p>
                Retention, MQTT, input devices, and other deployment settings are configured in
                config.yaml / add-on options.
            </p>
        </>
    );
}
