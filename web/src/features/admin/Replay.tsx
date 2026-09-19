import { ChangeEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { request } from "../../api/client";
import { errorText } from "./shared";

type Tone = { freq_hz: number; tol_pct: number; min_s: number; max_s: number | null };
type ToneSet = { id: string; name: string; enabled: boolean; sequence: Tone[] };
type Config = { tone_sets?: ToneSet[]; [key: string]: unknown };
type Upload = { id: string; file: File };
type ReplayItem = {
    id: string;
    recorded?: string[] | null;
    draft?: { toneset_id: string; detection_times: number[] }[];
    classification: string;
    reason?: string;
};
type ReplayResult = {
    items: ReplayItem[];
    summary: Record<string, number>;
    audio_seconds: number;
    audio_cap_seconds: number;
    limitations: string[];
};

const labels: Record<string, string> = {
    would_detect: "would detect",
    would_miss: "would miss",
    new_detection: "new detection",
    unchanged: "unchanged",
    skipped: "skipped",
};

function normalizeToneSet(item: ToneSet): ToneSet {
    return {
        ...item,
        sequence: item.sequence.map((tone) => ({
            freq_hz: Number(tone.freq_hz),
            tol_pct: Number(tone.tol_pct),
            min_s: Number(tone.min_s),
            max_s: tone.max_s === null ? null : Number(tone.max_s),
        })),
    };
}

export function Replay() {
    const [config, setConfig] = useState<Config | null>(null);
    const [draft, setDraft] = useState<ToneSet[]>([]);
    const [lastN, setLastN] = useState(1);
    const [useCalls, setUseCalls] = useState(true);
    const [uploads, setUploads] = useState<Upload[]>([]);
    const [result, setResult] = useState<ReplayResult | null>(null);
    const [error, setError] = useState("");
    const [advanced, setAdvanced] = useState("");
    const [uploading, setUploading] = useState(false);
    const fileInput = useRef<HTMLInputElement>(null);
    useEffect(() => {
        void Promise.resolve(request<Config>("config"))
            .then((value) => {
                setConfig(value);
                setDraft((value.tone_sets ?? []).map(normalizeToneSet));
            })
            .catch((reason: unknown) => setError(errorText(reason)));
    }, []);
    function updateToneSet(index: number, next: Partial<ToneSet>) {
        setDraft((items) => items.map((item, i) => (i === index ? { ...item, ...next } : item)));
    }
    function updateTone(index: number, toneIndex: number, key: keyof Tone, value: string) {
        setDraft((items) =>
            items.map((item, i) =>
                i !== index
                    ? item
                    : {
                          ...item,
                          sequence: item.sequence.map((tone, j) =>
                              j === toneIndex
                                  ? { ...tone, [key]: value === "" ? null : Number(value) }
                                  : tone,
                          ),
                      },
            ),
        );
    }
    async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
        const files = Array.from(event.target.files ?? []);
        event.target.value = "";
        setUploading(true);
        setError("");
        try {
            for (const file of files) {
                const body = new FormData();
                body.append("file", file);
                const uploaded = await request<{ id: string }>("admin/replay/uploads", {
                    method: "POST",
                    body,
                });
                setUploads((items) => [...items, { id: uploaded.id, file }]);
            }
        } catch (reason: unknown) {
            setError(errorText(reason));
        } finally {
            setUploading(false);
        }
    }
    async function runReplay() {
        setError("");
        try {
            const selected = advanced.trim()
                ? JSON.parse(advanced)
                : { ...config, tone_sets: draft };
            setResult(
                await request<ReplayResult>("admin/replay", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        draft: selected,
                        ...(useCalls ? { calls: { last_n: lastN } } : {}),
                        uploads: uploads.map((item) => item.id),
                    }),
                }),
            );
        } catch (reason: unknown) {
            const failure = reason as { status?: number };
            setError(
                failure.status === 404
                    ? `${errorText(reason)}. Re-upload the expired WAV.`
                    : errorText(reason),
            );
        }
    }
    return (
        <>
            <h1>Replay a draft</h1>
            <p>Build a temporary draft and test it without saving configuration.</p>
            {error && <p role="alert">{error}</p>}
            <section className="card">
                <h2>Draft tone sets</h2>
                {draft.map((item, index) => (
                    <fieldset key={item.id}>
                        <legend>{item.name}</legend>
                        <label>
                            Enabled
                            <input
                                type="checkbox"
                                checked={item.enabled}
                                onChange={(event) =>
                                    updateToneSet(index, { enabled: event.target.checked })
                                }
                            />
                        </label>
                        {item.sequence.map((tone, toneIndex) => (
                            <div key={`${item.id}-${toneIndex}`}>
                                <label>
                                    {item.name} tone {toneIndex + 1} frequency
                                    <input
                                        aria-label={`${item.name} tone ${toneIndex + 1} frequency`}
                                        type="number"
                                        value={tone.freq_hz}
                                        onChange={(event) =>
                                            updateTone(
                                                index,
                                                toneIndex,
                                                "freq_hz",
                                                event.target.value,
                                            )
                                        }
                                    />
                                </label>
                                <label>
                                    Tolerance
                                    <input
                                        type="number"
                                        value={tone.tol_pct}
                                        onChange={(event) =>
                                            updateTone(
                                                index,
                                                toneIndex,
                                                "tol_pct",
                                                event.target.value,
                                            )
                                        }
                                    />
                                </label>
                                <label>
                                    Minimum seconds
                                    <input
                                        type="number"
                                        value={tone.min_s}
                                        onChange={(event) =>
                                            updateTone(
                                                index,
                                                toneIndex,
                                                "min_s",
                                                event.target.value,
                                            )
                                        }
                                    />
                                </label>
                                <label>
                                    Maximum seconds
                                    <input
                                        type="number"
                                        value={tone.max_s ?? ""}
                                        onChange={(event) =>
                                            updateTone(
                                                index,
                                                toneIndex,
                                                "max_s",
                                                event.target.value,
                                            )
                                        }
                                    />
                                </label>
                            </div>
                        ))}
                    </fieldset>
                ))}
                <details>
                    <summary>Advanced: paste draft YAML/JSON</summary>
                    <textarea
                        aria-label="Draft YAML or JSON"
                        value={advanced}
                        onChange={(event) => setAdvanced(event.target.value)}
                    />
                </details>
                <Link to="/tonesets">Open in tone sets to save</Link>
            </section>
            <section className="card">
                <h2>Sources</h2>
                <label>
                    <input
                        type="checkbox"
                        checked={useCalls}
                        onChange={(event) => setUseCalls(event.target.checked)}
                    />
                    Use last N calls
                </label>
                <label>
                    Last N calls (1–50)
                    <input
                        type="number"
                        min={1}
                        max={50}
                        value={lastN}
                        onChange={(event) =>
                            setLastN(Math.min(50, Math.max(1, Number(event.target.value))))
                        }
                    />
                </label>
                <label>
                    Replay WAV files
                    <input
                        ref={fileInput}
                        aria-label="Replay WAV files"
                        type="file"
                        accept="audio/wav,.wav"
                        multiple
                        onChange={(event) => void uploadFiles(event)}
                    />
                </label>
                {uploading && <p>Uploading…</p>}
                {uploads.map((item) => (
                    <p key={item.id}>
                        {item.id} ({item.file.name}){" "}
                        <button
                            onClick={() =>
                                setUploads((items) =>
                                    items.filter((current) => current.id !== item.id),
                                )
                            }
                        >
                            Remove
                        </button>
                    </p>
                ))}
                <button onClick={() => void runReplay()} disabled={!config || uploading}>
                    Run replay
                </button>
            </section>
            {result && (
                <section className="card" aria-labelledby="replay-results-heading">
                    <h2 id="replay-results-heading">Results</h2>
                    <p>
                        Audio: {result.audio_seconds} / {result.audio_cap_seconds} seconds
                    </p>
                    {!result.items.length && <p>No calls or uploads matched.</p>}
                    <ul>
                        {Object.entries(result.summary).map(([key, count]) => (
                            <li key={key}>
                                {labels[key] ?? key}: {count}
                            </li>
                        ))}
                    </ul>
                    <h3>Limitations</h3>
                    <ul>
                        {result.limitations.map((item) => (
                            <li key={item}>{item}</li>
                        ))}
                    </ul>
                    <table>
                        <caption>Replay results</caption>
                        <thead>
                            <tr>
                                <th>Item</th>
                                <th>Recorded</th>
                                <th>Draft detections</th>
                                <th>Classification</th>
                                <th>Reason</th>
                            </tr>
                        </thead>
                        <tbody>
                            {result.items.map((item) => (
                                <tr key={item.id}>
                                    <th>{item.id}</th>
                                    <td>{item.recorded?.join(", ") ?? "—"}</td>
                                    <td>
                                        {item.draft
                                            ?.map(
                                                (detection) =>
                                                    `${detection.toneset_id} at ${detection.detection_times.join(", ")}s`,
                                            )
                                            .join(", ") ?? "—"}
                                    </td>
                                    <td>
                                        <span>
                                            {labels[item.classification] ?? item.classification}
                                        </span>
                                    </td>
                                    <td>{item.reason ?? "—"}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </section>
            )}
        </>
    );
}
