import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { request } from "../../api/client";
type Tone = { frequency: number; tolerance_pct: number; min_s: number; max_s: number | null };
type ToneSet = { id: string; name: string; enabled: boolean; sequence: Tone[] };
type ImportTone = { freq_hz: number; tol_pct: number; min_s: number };
type ImportRow = {
    name: string;
    status: "imported" | "skipped";
    tone_set: { name: string; sequence: ImportTone[] } | null;
    notes: string[];
    errors: string[];
};
type ImportPreview = { imported: number; skipped: number; sections: ImportRow[] };
export function ToneSets() {
    const [items, setItems] = useState<ToneSet[]>([]);
    const [preview, setPreview] = useState<ImportPreview | null>(null);
    const [importFile, setImportFile] = useState<File | null>(null);
    const [importError, setImportError] = useState("");
    const fileInput = useRef<HTMLInputElement>(null);
    const reload = () =>
        request<ToneSet[]>("tonesets")
            .then(setItems)
            .catch(() => undefined);
    useEffect(() => {
        void reload();
    }, []);
    async function previewImport(event: ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0];
        event.target.value = "";
        if (!file) return;
        setImportFile(file);
        setImportError("");
        const body = new FormData();
        body.append("file", file);
        try {
            setPreview(await request<ImportPreview>("import/tones-cfg", { method: "POST", body }));
        } catch {
            setImportError("Unable to preview this tones.cfg file.");
        }
    }
    async function applyImport(mode: "merge" | "replace") {
        if (!importFile) return;
        if (
            mode === "replace" &&
            !window.confirm("Replace all current tone sets with this import?")
        )
            return;
        const body = new FormData();
        body.append("file", importFile);
        try {
            await request(`import/tones-cfg?apply=true&mode=${mode}`, { method: "POST", body });
            setPreview(null);
            setImportFile(null);
            await reload();
        } catch {
            setImportError("Unable to apply this tones.cfg file.");
        }
    }
    return (
        <>
            <h1>Tone sets</h1>
            <Link to="/tonesets/new">
                <button>New tone set</button>
            </Link>
            <button onClick={() => fileInput.current?.click()}>Import legacy tones.cfg</button>
            <input
                ref={fileInput}
                aria-label="tones.cfg file"
                type="file"
                accept=".cfg,text/plain"
                onChange={previewImport}
                hidden
            />
            {importError && (
                <p className="error" role="alert">
                    {importError}
                </p>
            )}
            {preview && (
                <section aria-labelledby="tones-cfg-preview-heading">
                    <h2 id="tones-cfg-preview-heading">tones.cfg import preview</h2>
                    <p>
                        {preview.imported} imported, {preview.skipped} skipped
                    </p>
                    <table>
                        <caption>Proposed tone sets</caption>
                        <thead>
                            <tr>
                                <th scope="col">Name</th>
                                <th scope="col">Tones</th>
                                <th scope="col">Tolerance</th>
                                <th scope="col">Notes and errors</th>
                            </tr>
                        </thead>
                        <tbody>
                            {preview.sections.map((row) => (
                                <tr key={row.name}>
                                    <th scope="row">{row.tone_set?.name ?? row.name}</th>
                                    <td>
                                        {row.tone_set?.sequence
                                            .map((tone) => `${tone.freq_hz} Hz / ${tone.min_s} s`)
                                            .join(", ") ?? "—"}
                                    </td>
                                    <td>
                                        {row.tone_set?.sequence
                                            .map((tone) => `${tone.tol_pct}%`)
                                            .join(", ") ?? "—"}
                                    </td>
                                    <td>
                                        <ul>
                                            {[...row.notes, ...row.errors].map((message, index) => (
                                                <li key={`${row.name}-${index}`}>{message}</li>
                                            ))}
                                        </ul>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                    <button onClick={() => void applyImport("merge")} disabled={!preview.imported}>
                        Merge
                    </button>
                    <button
                        onClick={() => void applyImport("replace")}
                        disabled={!preview.imported}
                    >
                        Replace
                    </button>
                </section>
            )}
            {items.map((i) => (
                <div className="card" key={i.id}>
                    <b>{i.name}</b>
                    <label htmlFor={`enabled-${i.id}`}>
                        Enabled
                        <input
                            id={`enabled-${i.id}`}
                            type="checkbox"
                            checked={i.enabled}
                            onChange={() =>
                                request(`tonesets/${i.id}`, {
                                    method: "PUT",
                                    headers: { "Content-Type": "application/json" },
                                    body: JSON.stringify({ ...i, enabled: !i.enabled }),
                                }).then(reload)
                            }
                        />
                    </label>
                    <Link to={`/tonesets/${i.id}/edit`}>Edit</Link>
                    <button
                        className="danger"
                        onClick={async () => {
                            if (window.confirm(`Delete ${i.name}?`))
                                try {
                                    await request(`tonesets/${i.id}`, { method: "DELETE" });
                                    void reload();
                                } catch (e) {
                                    if ((e as { status?: number }).status === 409)
                                        window.alert(
                                            "Referenced by: " +
                                                (
                                                    (
                                                        e as {
                                                            body?: {
                                                                detail?: { referrers?: string[] };
                                                            };
                                                        }
                                                    ).body?.detail?.referrers ?? []
                                                ).join(", "),
                                        );
                                }
                        }}
                    >
                        Delete
                    </button>
                    <button onClick={() => request(`tonesets/${i.id}/test`, { method: "POST" })}>
                        Test
                    </button>
                </div>
            ))}
        </>
    );
}
export function ToneSetForm() {
    const { id } = useParams();
    const [params] = useSearchParams();
    const location = useLocation();
    const nav = useNavigate();
    const [name, setName] = useState("");
    const [tones, setTones] = useState<Tone[]>([
        {
            frequency: Number(params.get("freq_hz")) || 1000,
            tolerance_pct: 1,
            min_s: 0.5,
            max_s: 3,
        },
    ]);
    const [error, setError] = useState("");
    useEffect(() => {
        const state = location.state as { draft?: ToneSet; discoveredToneId?: number } | null;
        if (!state?.draft) return;
        setName(state.draft.name);
        setTones(
            state.draft.sequence.map((tone) => ({
                frequency: (tone as Tone & { freq_hz?: number }).freq_hz ?? tone.frequency,
                tolerance_pct: (tone as Tone & { tol_pct?: number }).tol_pct ?? tone.tolerance_pct,
                min_s: tone.min_s,
                max_s: tone.max_s ?? null,
            })),
        );
    }, [location.state]);
    useEffect(() => {
        if (id)
            request<ToneSet>(`tonesets/${id}`)
                .then((i) => {
                    setName(i.name);
                    setTones(
                        i.sequence.map((tone) => ({
                            frequency:
                                (tone as Tone & { freq_hz?: number }).freq_hz ?? tone.frequency,
                            tolerance_pct:
                                (tone as Tone & { tol_pct?: number }).tol_pct ?? tone.tolerance_pct,
                            min_s: tone.min_s,
                            max_s: tone.max_s,
                        })),
                    );
                })
                .catch(() => undefined);
    }, [id]);
    async function save(e: FormEvent) {
        e.preventDefault();
        if (
            tones.some(
                (t) =>
                    t.frequency < 250 ||
                    t.frequency > 3000 ||
                    t.tolerance_pct < 0.1 ||
                    t.tolerance_pct > 10 ||
                    (t.max_s !== null && t.max_s < t.min_s),
            )
        ) {
            setError("Check frequency, tolerance, and duration ranges.");
            return;
        }
        try {
            await request(`tonesets${id ? `/${id}` : ""}`, {
                method: id ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    id: id ?? crypto.randomUUID(),
                    name,
                    enabled: true,
                    sequence: tones.map(({ frequency, tolerance_pct, min_s, max_s }) => ({
                        freq_hz: frequency,
                        tol_pct: tolerance_pct,
                        min_s,
                        max_s,
                    })),
                    ...((location.state as { discoveredToneId?: number } | null)?.discoveredToneId
                        ? {
                              discovered_tone_id: (location.state as { discoveredToneId: number })
                                  .discoveredToneId,
                          }
                        : {}),
                }),
            });
            nav("/tonesets");
        } catch (e) {
            const d = (e as { body?: { detail?: { loc?: (string | number)[]; msg?: string }[] } })
                .body?.detail;
            setError(
                d?.map((x) => `${x.loc?.join(".")}: ${x.msg}`).join("; ") ??
                    "Unable to save tone set",
            );
        }
    }
    return (
        <>
            <h1>{id ? "Edit" : "Create"} tone set</h1>
            <form className="form" onSubmit={save}>
                <label htmlFor="name">
                    Name
                    <input
                        id="name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        required
                    />
                </label>
                {tones.map((t, i) => (
                    <fieldset key={i}>
                        <legend>Tone {i + 1}</legend>
                        {(["frequency", "tolerance_pct", "min_s", "max_s"] as const).map((f) => (
                            <label key={f} htmlFor={`${f}-${i}`}>
                                {f}
                                <input
                                    id={`${f}-${i}`}
                                    type="number"
                                    step="any"
                                    value={t[f] ?? ""}
                                    onChange={(e) =>
                                        setTones((a) =>
                                            a.map((x, j) =>
                                                j === i ? { ...x, [f]: Number(e.target.value) } : x,
                                            ),
                                        )
                                    }
                                />
                            </label>
                        ))}
                    </fieldset>
                ))}
                <button>Save</button>
                {error && (
                    <p className="error" role="alert">
                        {error}
                    </p>
                )}
            </form>
        </>
    );
}
