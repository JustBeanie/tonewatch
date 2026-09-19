import { useEffect, useState } from "react";
import { download } from "./download";
import { request } from "../../api/client";
import { errorText } from "./shared";

export function Backup() {
    const [recordings, setRecordings] = useState(false);
    const [credentials, setCredentials] = useState(false);
    const [ingress, setIngress] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    useEffect(() => {
        void Promise.resolve(request<{ via?: string }>("auth/status"))
            .then((status) => setIngress(status.via === "ingress"))
            .catch(() => undefined);
    }, []);
    async function createBackup() {
        setBusy(true);
        setError("");
        try {
            await download("admin/backup", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    include_recordings: recordings,
                    include_credentials: credentials,
                }),
            });
        } catch (reason: unknown) {
            setError(errorText(reason));
        } finally {
            setBusy(false);
        }
    }
    return (
        <>
            <h1>Backup</h1>
            {error && <p role="alert">{error}</p>}
            <section className="card">
                <h2>Create archive</h2>
                <label>
                    <input
                        type="checkbox"
                        aria-label="Include recordings"
                        checked={recordings}
                        onChange={(event) => setRecordings(event.target.checked)}
                    />
                    Include recordings
                </label>
                {!ingress && (
                    <label>
                        <input
                            type="checkbox"
                            aria-label="Include credentials"
                            checked={credentials}
                            onChange={(event) => setCredentials(event.target.checked)}
                        />
                        Include credentials
                    </label>
                )}
                <p>
                    The archive contains configuration secrets. Store it like a password. Including
                    credentials also adds the API token and UI password.
                </p>
                {ingress && <p>Credentials are unavailable through ingress.</p>}
                <button onClick={() => void createBackup()} disabled={busy}>
                    {busy ? "Preparing backup…" : "Download backup"}
                </button>
            </section>
            <section className="card">
                <h2>Restore from an archive</h2>
                <p>Restore is CLI-only. Stop the ToneWatch server before running these commands.</p>
                <pre>
                    <code>tonewatch backup restore FILE --dry-run</code>
                </pre>
                <p>Review the manifest and compatibility result, then run the restore for real:</p>
                <pre>
                    <code>tonewatch backup restore FILE</code>
                </pre>
                <p>
                    Existing archive-owned files are moved aside into a <code>pre-restore-*</code>
                    directory before replacement, so the prior state remains available for rollback.
                </p>
            </section>
        </>
    );
}
