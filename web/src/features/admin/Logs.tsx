import { useEffect, useRef, useState } from "react";
import { request } from "../../api/client";
import { errorText } from "./shared";
import { download } from "./download";
type Row = { seq?: number; level?: string; message?: string; [key: string]: unknown };
export function Logs() {
    const [rows, setRows] = useState<Row[]>([]);
    const [level, setLevel] = useState("INFO");
    const [paused, setPaused] = useState(false);
    const [error, setError] = useState("");
    const last = useRef<number | undefined>(undefined);
    useEffect(() => {
        let timer: number | undefined;
        let active = true;
        const load = async () => {
            if (!active || paused || document.hidden) return;
            try {
                const query = new URLSearchParams({ level, limit: "500" });
                if (last.current !== undefined) query.set("since_seq", String(last.current));
                const result = await request<{ items: Row[] }>(`admin/logs?${query}`);
                if (result.items.length)
                    last.current = Number(result.items.at(-1)?.seq ?? last.current);
                setRows((current) => [...current, ...result.items].slice(-2000));
            } catch (e) {
                setError(errorText(e));
            }
        };
        const tick = () => {
            void load();
            timer = window.setTimeout(tick, 3000);
        };
        const visibility = () => {
            if (!document.hidden && !paused) void load();
        };
        document.addEventListener("visibilitychange", visibility);
        tick();
        return () => {
            active = false;
            if (timer) window.clearTimeout(timer);
            document.removeEventListener("visibilitychange", visibility);
        };
    }, [level, paused]);
    return (
        <>
            <h1>Logs and support</h1>
            <section className="card">
                <label>
                    Level
                    <select value={level} onChange={(e) => setLevel(e.target.value)}>
                        <option>DEBUG</option>
                        <option>INFO</option>
                        <option>WARNING</option>
                        <option>ERROR</option>
                    </select>
                </label>
                <button onClick={() => setPaused(!paused)}>{paused ? "Resume" : "Pause"}</button>
                {error && <p role="alert">{error}</p>}
                <pre>
                    {rows.map((row, index) => (
                        <span key={`${row.seq ?? index}-${index}`}>
                            {String(row.message ?? JSON.stringify(row))}
                            {"\n"}
                        </span>
                    ))}
                </pre>
            </section>
            <section className="card">
                <h2>Support bundle</h2>
                <p>
                    Contains redacted config, health, recent logs, detections, and environment
                    details; excludes recordings, secrets, and addresses.
                </p>
                <button
                    onClick={() =>
                        void download("admin/support-bundle", { method: "POST" }).catch((e) =>
                            setError(errorText(e)),
                        )
                    }
                >
                    Download support bundle
                </button>
            </section>
        </>
    );
}
