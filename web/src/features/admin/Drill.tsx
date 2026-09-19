import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router";
import { request } from "../../api/client";
import { useWsEvents } from "../../lib/ws";
import { errorText } from "./shared";

type Source = { id: string; name?: string; enabled?: boolean };
type ToneSet = { id: string; name?: string; enabled?: boolean };
type Health = { sources: { id: string; realtime_factor?: number | null }[] };

export function Drill() {
    const [sources, setSources] = useState<Source[]>([]);
    const [tonesets, setTonesets] = useState<ToneSet[]>([]);
    const [selected, setSelected] = useState({
        source_id: "",
        toneset_id: "",
        mode: "replace",
        voice_s: "5",
        keep: false,
    });
    const [confirm, setConfirm] = useState(false);
    const [result, setResult] = useState<{ drill_id: string; expected_duration_s: number }>();
    const [message, setMessage] = useState("");
    const [event, setEvent] = useState("");
    useEffect(() => {
        Promise.all([
            request<Source[]>("sources"),
            request<ToneSet[]>("tonesets"),
            request<Health>("admin/health"),
        ])
            .then(([allSources, allTonesets, health]) => {
                const running = new Set(health.sources.map((s) => s.id));
                setSources(
                    allSources.filter(
                        (source) => source.enabled !== false && running.has(source.id),
                    ),
                );
                setTonesets(allTonesets.filter((tone) => tone.enabled !== false));
            })
            .catch((error: unknown) => setMessage(errorText(error)));
    }, []);
    useWsEvents("events", (incoming) => {
        if (
            result &&
            String(incoming.data?.drill_id ?? incoming.data?.call_id ?? "") === result.drill_id
        )
            setEvent("Drill call received; open the calls list to inspect it.");
    });
    async function start() {
        setMessage("");
        setConfirm(false);
        try {
            const response = await request<{ drill_id: string; expected_duration_s: number }>(
                "admin/drill",
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ ...selected, voice_s: Number(selected.voice_s) }),
                },
            );
            setResult(response);
        } catch (error) {
            setMessage(errorText(error));
        }
    }
    function submit(e: FormEvent) {
        e.preventDefault();
        setConfirm(true);
    }
    return (
        <>
            <h1>Run an admin drill</h1>
            <p>
                This sends a synthetic tone through a running source and every configured alert
                target.
            </p>
            <form className="form" onSubmit={submit}>
                <label>
                    Running source
                    <select
                        aria-label="Source"
                        value={selected.source_id}
                        onChange={(e) => setSelected({ ...selected, source_id: e.target.value })}
                        required
                    >
                        <option value="">Choose a source</option>
                        {sources.map((s) => (
                            <option key={s.id} value={s.id}>
                                {s.name ?? s.id}
                            </option>
                        ))}
                    </select>
                </label>
                <label>
                    Tone set
                    <select
                        aria-label="Tone set"
                        value={selected.toneset_id}
                        onChange={(e) => setSelected({ ...selected, toneset_id: e.target.value })}
                        required
                    >
                        <option value="">Choose a tone set</option>
                        {tonesets.map((s) => (
                            <option key={s.id} value={s.id}>
                                {s.name ?? s.id}
                            </option>
                        ))}
                    </select>
                </label>
                <label>
                    Mode
                    <select
                        value={selected.mode}
                        onChange={(e) => setSelected({ ...selected, mode: e.target.value })}
                    >
                        <option value="replace">Replace — use only the drill signal</option>
                        <option value="mix">Mix — overlay the drill signal on live audio</option>
                    </select>
                </label>
                <label>
                    Voice seconds
                    <input
                        type="number"
                        min="0"
                        max="20"
                        step="0.1"
                        value={selected.voice_s}
                        onChange={(e) => setSelected({ ...selected, voice_s: e.target.value })}
                    />
                </label>
                <label>
                    <input
                        type="checkbox"
                        checked={selected.keep}
                        onChange={(e) => setSelected({ ...selected, keep: e.target.checked })}
                    />{" "}
                    Keep this call
                </label>
                <button type="submit">Start drill</button>
            </form>
            {confirm && (
                <div role="dialog" aria-modal="true" className="card">
                    <h2>Confirm drill</h2>
                    <p>This sends real alerts to every configured target, marked DRILL.</p>
                    <button onClick={() => void start()}>Send drill</button>
                    <button className="secondary" onClick={() => setConfirm(false)}>
                        Cancel
                    </button>
                </div>
            )}
            {message && <p role="alert">{message}</p>}
            {result && (
                <section className="card">
                    <p>Expected duration: {result.expected_duration_s.toFixed(1)} seconds.</p>
                    <Link to="/calls">Open calls list</Link>
                    {event && <p role="status">{event}</p>}
                </section>
            )}
        </>
    );
}
