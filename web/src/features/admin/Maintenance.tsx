import { useState } from "react";
import { request } from "../../api/client";
import { errorText, formatBytes } from "./shared";

type Retention = {
    recordings?: { files?: number; bytes?: number };
    calls?: number;
    cad_incidents?: number;
    discovered?: number;
};
type Orphans = {
    files: Array<{ path: string; bytes: number }>;
    missing_rows: Array<{ id: number; path: string }>;
    invalid_rows: Array<{ id: number }>;
    file_count: number;
    row_count: number;
    bytes: number;
};
export function Maintenance() {
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");
    const [retention, setRetention] = useState<Retention | null>(null);
    const [orphans, setOrphans] = useState<Orphans | null>(null);
    const [deleteFiles, setDeleteFiles] = useState(false);
    const [deleteRows, setDeleteRows] = useState(false);
    const [db, setDb] = useState<{ before_bytes: number; after_bytes: number } | null>(null);
    async function act<T>(path: string, body?: unknown): Promise<T | undefined> {
        setBusy(true);
        setError("");
        try {
            return await request<T>(path, {
                method: "POST",
                ...(body === undefined ? {} : { body: JSON.stringify(body) }),
            });
        } catch (reason: unknown) {
            const text = errorText(reason);
            setError(
                (reason as { status?: number }).status === 409
                    ? text.includes("counts")
                        ? "Changed since preview, preview again"
                        : "Maintenance operation already running"
                    : text,
            );
            return undefined;
        } finally {
            setBusy(false);
        }
    }
    async function previewRetention() {
        setRetention((await act<Retention>("admin/maintenance/retention/preview")) ?? null);
    }
    async function runRetention() {
        if (
            !retention ||
            !window.confirm(
                `Run now? This will process ${retention.recordings?.files ?? 0} files, ${formatBytes(retention.recordings?.bytes)}, ${retention.calls ?? 0} calls, ${retention.cad_incidents ?? 0} CAD incidents, and ${retention.discovered ?? 0} discovered.`,
            )
        )
            return;
        await act("admin/maintenance/retention/run");
        setRetention(null);
    }
    async function previewOrphans() {
        setOrphans((await act<Orphans>("admin/maintenance/orphans/preview")) ?? null);
    }
    async function applyOrphans() {
        if (!orphans || (!deleteFiles && !deleteRows) || !window.confirm("Apply orphan cleanup?"))
            return;
        await act("admin/maintenance/orphans/apply", {
            delete_files: deleteFiles,
            delete_rows: deleteRows,
            expected_counts: { file_count: orphans.file_count, row_count: orphans.row_count },
        });
        setOrphans(null);
    }
    return (
        <>
            <h1>Maintenance</h1>
            {error && <p role="alert">{error}</p>}
            <section className="card">
                <h2>Retention</h2>
                <button disabled={busy} onClick={() => void previewRetention()}>
                    Preview
                </button>
                <button disabled={busy || !retention} onClick={() => void runRetention()}>
                    Run now
                </button>
                {retention && (
                    <dl>
                        <dt>Files</dt>
                        <dd>{retention.recordings?.files ?? 0}</dd>
                        <dt>Bytes</dt>
                        <dd>{formatBytes(retention.recordings?.bytes)}</dd>
                        <dt>Calls</dt>
                        <dd>{retention.calls ?? 0}</dd>
                        <dt>CAD incidents</dt>
                        <dd>{retention.cad_incidents ?? 0}</dd>
                        <dt>Discovered</dt>
                        <dd>{retention.discovered ?? 0}</dd>
                    </dl>
                )}
            </section>
            <section className="card">
                <h2>Database</h2>
                <button
                    disabled={busy}
                    onClick={() =>
                        void act<{ before_bytes: number; after_bytes: number }>(
                            "admin/maintenance/database/checkpoint",
                        ).then((v) => v && setDb(v))
                    }
                >
                    Checkpoint
                </button>
                <button
                    disabled={busy}
                    onClick={() => {
                        if (window.confirm("Vacuum the database?"))
                            void act<{ before_bytes: number; after_bytes: number }>(
                                "admin/maintenance/database/vacuum",
                            ).then((v) => v && setDb(v));
                    }}
                >
                    Vacuum
                </button>
                {db && (
                    <p>
                        Before {formatBytes(db.before_bytes)}; after {formatBytes(db.after_bytes)}.
                    </p>
                )}
            </section>
            <section className="card">
                <h2>Orphans</h2>
                <button disabled={busy} onClick={() => void previewOrphans()}>
                    Preview
                </button>
                {orphans && (
                    <>
                        <p>
                            {orphans.file_count} files ({formatBytes(orphans.bytes)}),{" "}
                            {orphans.row_count} rows missing files.
                        </p>
                        {orphans.invalid_rows.length > 0 && (
                            <p role="alert">
                                Warning: {orphans.invalid_rows.length} invalid rows were found.
                            </p>
                        )}
                        <ul>
                            {orphans.files.map((file) => (
                                <li key={file.path}>
                                    {file.path} — {formatBytes(file.bytes)}
                                </li>
                            ))}
                            {orphans.missing_rows.map((row) => (
                                <li key={row.id}>Missing file: {row.path}</li>
                            ))}
                        </ul>
                        <label>
                            <input
                                type="checkbox"
                                checked={deleteFiles}
                                onChange={(e) => setDeleteFiles(e.target.checked)}
                            />{" "}
                            Delete files
                        </label>
                        <label>
                            <input
                                type="checkbox"
                                checked={deleteRows}
                                onChange={(e) => setDeleteRows(e.target.checked)}
                            />{" "}
                            Delete rows
                        </label>
                        <button
                            disabled={busy || (!deleteFiles && !deleteRows)}
                            onClick={() => void applyOrphans()}
                        >
                            Apply
                        </button>
                    </>
                )}
            </section>
        </>
    );
}
