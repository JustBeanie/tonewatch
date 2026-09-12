import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { request } from "../../api/client";
import { ToneWatchSocket, WsMessage } from "../../lib/ws";
export function Spectrum() {
    const [sources, setSources] = useState<{ id: string; name?: string }[]>([]);
    const [source, setSource] = useState("");
    const [m, setM] = useState<WsMessage>();
    const [paused, setPaused] = useState(false);
    const [announcement, setAnnouncement] = useState("");
    const last = useRef(0);
    const nav = useNavigate();
    const canvas = useRef<HTMLCanvasElement>(null);
    useEffect(() => {
        request<typeof sources>("sources")
            .then(setSources)
            .catch(() => undefined);
    }, []);
    useEffect(() => {
        if (!source) return;
        const s = new ToneWatchSocket();
        s.connect();
        s.subscribe(`spectrum:${source}`);
        const off = s.onMessage((x) => {
            if (!paused && x.type === "SpectrumUpdate") {
                setM(x);
                const now = Date.now();
                if (now - last.current >= 1000) {
                    setAnnouncement(
                        `${Number(x.data?.dominant_hz ?? 0).toFixed(1)} hertz dominant`,
                    );
                    last.current = now;
                }
            }
        });
        return () => {
            off();
            s.unsubscribe(`spectrum:${source}`);
            s.close();
        };
    }, [source, paused]);
    useEffect(() => {
        const c = canvas.current;
        if (!c) return;
        const ctx = c.getContext("2d");
        if (ctx) {
            ctx.clearRect(0, 0, c.width, c.height);
            ctx.strokeStyle = "#2563eb";
            ctx.beginPath();
            ctx.moveTo(0, c.height);
            ctx.lineTo(c.width / 2, c.height / 3);
            ctx.lineTo(c.width, c.height);
            ctx.stroke();
        }
    }, [m]);
    const freq = Number(m?.data?.dominant_hz ?? 0);
    return (
        <>
            <h1>Spectrum</h1>
            <label htmlFor="spectrum-source">
                Source
                <select
                    id="spectrum-source"
                    value={source}
                    onChange={(e) => setSource(e.target.value)}
                >
                    <option value="">Choose a source</option>
                    {sources.map((s) => (
                        <option key={s.id} value={s.id}>
                            {s.name ?? s.id}
                        </option>
                    ))}
                </select>
            </label>
            <canvas
                ref={canvas}
                width="700"
                height="220"
                aria-label="Magnitude spectrum plot from 250 to 3000 Hz"
            />
            <p>250 Hz — magnitude — 3000 Hz</p>
            <p>Dominant frequency: {freq.toFixed(1)} Hz</p>
            <p>
                Purity: {Number(m?.data?.purity ?? 0).toFixed(1)} · Level:{" "}
                {Number(m?.data?.dbfs ?? -100).toFixed(1)} dBFS
            </p>
            <button onClick={() => setPaused(!paused)}>{paused ? "Resume" : "Pause"}</button>
            <button onClick={() => nav(`/tonesets/new?freq_hz=${freq}`)}>Capture tone</button>
            <p className="visually-hidden" aria-live="polite">
                {announcement}
            </p>
        </>
    );
}
