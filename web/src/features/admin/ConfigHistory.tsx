import { useEffect, useState } from "react";
import { request } from "../../api/client";
import { apiUrl } from "../../lib/urls";
import { errorText } from "./shared";
import { DiffView } from "./Audit";
import { download } from "./download";

type Version = { id: string; time: string; actor: string; route: string; sha256: string };
type Change = { path: string; before?: unknown; after?: unknown };
async function configWithEtag(): Promise<string> {
    const response = await fetch(apiUrl("config"), { credentials: "same-origin" });
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    return response.headers.get("ETag") ?? "";
}
export function ConfigHistory() {
    const [versions, setVersions] = useState<Version[]>([]);
    const [selected, setSelected] = useState("");
    const [changes, setChanges] = useState<Change[]>([]);
    const [error, setError] = useState("");
    const [confirm, setConfirm] = useState(false);
    const [secretPrompt, setSecretPrompt] = useState(false);
    const [secretConfirm, setSecretConfirm] = useState("");
    const [content, setContent] = useState("");
    const [preview, setPreview] = useState<Change[] | null>(null);
    const [previewContent, setPreviewContent] = useState("");
    useEffect(() => {
        void request<Version[]>("admin/config/versions")
            .then(setVersions)
            .catch((e) => setError(errorText(e)));
    }, []);
    useEffect(() => {
        if (selected)
            void request<Change[]>(`admin/config/versions/${selected}/diff`)
                .then(setChanges)
                .catch((e) => setError(errorText(e)));
    }, [selected]);
    async function rollback() {
        try {
            const etag = await configWithEtag();
            await request(`admin/config/versions/${selected}/rollback`, {
                method: "POST",
                headers: { "If-Match": etag },
            });
            setConfirm(false);
            setError("Rolled back successfully; reload the page to see the new current version.");
        } catch (e) {
            setConfirm(false);
            setError(
                (e as { status?: number }).status === 412
                    ? "Configuration changed elsewhere, reload."
                    : (e as { status?: number }).status === 428
                      ? "Bug-level error: rollback requires If-Match."
                      : errorText(e),
            );
        }
    }
    async function previewImport() {
        try {
            const response = await request<{ diff: Change[] }>("admin/config/import/preview", {
                method: "POST",
                headers: { "Content-Type": "text/plain" },
                body: content,
            });
            setPreview(response.diff);
            setPreviewContent(content);
        } catch (e) {
            setPreview(null);
            setError(errorText(e));
        }
    }
    async function applyImport() {
        if (!preview || previewContent !== content) return;
        try {
            const etag = await configWithEtag();
            await request("admin/config/import/apply", {
                method: "POST",
                headers: { "Content-Type": "text/plain", "If-Match": etag },
                body: content,
            });
            setError("Configuration imported.");
        } catch (e) {
            setError(errorText(e));
        }
    }
    return (
        <>
            <h1>Configuration history</h1>
            {error && <p role="alert">{error}</p>}
            <section className="card">
                <table>
                    <thead>
                        <tr>
                            <th>Time</th>
                            <th>Actor</th>
                            <th>Route</th>
                            <th>Hash</th>
                        </tr>
                    </thead>
                    <tbody>
                        {versions.map((v) => (
                            <tr key={v.id} onClick={() => setSelected(v.id)}>
                                <td>{new Date(v.time).toLocaleString()}</td>
                                <td>{v.actor}</td>
                                <td>{v.route}</td>
                                <td>{v.sha256.slice(0, 8)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                {!versions.length && <p>No configuration versions.</p>}
            </section>
            {selected && (
                <section className="card">
                    <h2>Diff against current</h2>
                    <DiffView rows={changes} />
                    <button onClick={() => setConfirm(true)}>Roll back to this version</button>
                </section>
            )}
            {confirm && (
                <div role="dialog">
                    <p>Roll back this configuration?</p>
                    <button onClick={rollback}>Confirm rollback</button>
                    <button onClick={() => setConfirm(false)}>Cancel</button>
                </div>
            )}
            <section className="card">
                <h2>Export</h2>
                <button onClick={() => void download("admin/config/export?format=yaml")}>
                    Download masked config
                </button>
                <button
                    onClick={() => {
                        setSecretPrompt(true);
                        setSecretConfirm("");
                    }}
                >
                    Include secrets
                </button>
                {secretPrompt && (
                    <div>
                        <p>
                            This download contains plaintext secrets. Type include-secrets to
                            confirm.
                        </p>
                        <input
                            aria-label="Secret export confirmation"
                            value={secretConfirm}
                            onChange={(e) => setSecretConfirm(e.target.value)}
                        />
                        <button
                            disabled={secretConfirm !== "include-secrets"}
                            onClick={() =>
                                void download("admin/config/export", {
                                    method: "POST",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({
                                        format: "yaml",
                                        include_secrets: true,
                                        confirm: "include-secrets",
                                    }),
                                })
                            }
                        >
                            Download plaintext secrets
                        </button>
                    </div>
                )}
            </section>
            <section className="card">
                <h2>Import</h2>
                <textarea
                    aria-label="Configuration content"
                    value={content}
                    onChange={(e) => {
                        setContent(e.target.value);
                        setPreview(null);
                    }}
                />
                <button onClick={() => void previewImport()}>Preview</button>
                <button
                    disabled={!preview || previewContent !== content}
                    onClick={() => void applyImport()}
                >
                    Apply
                </button>
                {preview && <DiffView rows={preview} />}
            </section>
        </>
    );
}
