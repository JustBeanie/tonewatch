import { useEffect, useRef, useState } from "react";
import { request } from "../../api/client";
import type { WsMessage } from "../../lib/ws";

export type Source = {
    id: string;
    name?: string;
    type: string;
    path?: string;
    device?: string;
    channel?: number;
    url?: string;
    frequency_hz?: number;
    gain?: number;
    ppm?: number;
    rtl_fm_squelch?: number;
    enabled?: boolean;
    live_stream_enabled?: boolean;
    squelch?: SquelchConfig;
    live_listeners?: number | null;
    squelch_open?: boolean | null;
    squelch_mode_effective?: string | null;
    noise_floor_dbfs?: number | null;
    open_dbfs_effective?: number | null;
    close_dbfs_effective?: number | null;
    calibrating?: boolean | null;
    stuck_open?: boolean | null;
    chatter?: boolean | null;
    transitions_per_min?: number | null;
};

export type SquelchConfig = {
    mode: "off" | "level" | "noise_floor" | "auto";
    open_dbfs: number;
    close_dbfs: number;
    attack_ms: number;
    hang_ms: number;
    floor_margin_db: number;
    auto_window_s: number;
    auto_min_samples_s: number;
    auto_k: number;
    min_margin_db: number;
    max_margin_db: number;
    stuck_open_s: number;
    max_transitions_per_min: number;
};

const defaults: SquelchConfig = {
    mode: "off",
    open_dbfs: -40,
    close_dbfs: -45,
    attack_ms: 50,
    hang_ms: 1500,
    floor_margin_db: 10,
    auto_window_s: 300,
    auto_min_samples_s: 30,
    auto_k: 1.5,
    min_margin_db: 6,
    max_margin_db: 25,
    stuck_open_s: 600,
    max_transitions_per_min: 20,
};

function errorText(error: unknown): string {
    const body = (error as { body?: { detail?: unknown } }).body?.detail;
    if (Array.isArray(body))
        return body
            .map((item) => {
                const detail = item as { loc?: (string | number)[]; msg?: string };
                return `${detail.loc?.join(".") ?? "source"}: ${detail.msg ?? "invalid value"}`;
            })
            .join("; ");
    return typeof body === "string" ? body : (error as Error).message;
}

export function LivePlayer({
    source,
    message,
}: {
    source: Source;
    message: WsMessage | undefined;
}) {
    const [url, setUrl] = useState<string>();
    const [expires, setExpires] = useState<number>();
    const [error, setError] = useState("");
    const [statusCount, setStatusCount] = useState<number | null>();
    const audio = useRef<HTMLAudioElement>(null);
    const event = message;
    const count =
        event?.type === "live_listeners_changed" && event.data?.source_id === source.id
            ? Number(event.data.source_listeners)
            : (statusCount ?? source.live_listeners);
    useEffect(() => {
        if (!expires) return;
        const timer = window.setInterval(() => setExpires((value) => value), 1000);
        return () => window.clearInterval(timer);
    }, [expires]);
    useEffect(() => {
        if (!url || !audio.current) return;
        audio.current.src = url;
        audio.current.load();
        void Promise.resolve(audio.current.play()).catch(() => undefined);
    }, [url]);
    useEffect(() => {
        if (!url) return;
        let active = true;
        const refresh = () => {
            void request<Source>(`sources/${encodeURIComponent(source.id)}`)
                .then((current) => {
                    if (active && current.live_listeners !== undefined) {
                        setStatusCount(current.live_listeners);
                    }
                })
                .catch(() => undefined);
        };
        refresh();
        const timer = window.setInterval(refresh, 250);
        return () => {
            active = false;
            window.clearInterval(timer);
        };
    }, [source.id, url]);
    async function start() {
        setError("");
        try {
            const result = await request<{ url: string; expires_at: number }>(
                `sources/${encodeURIComponent(source.id)}/live-url`,
                { method: "POST" },
            );
            setUrl(result.url);
            setExpires(result.expires_at);
        } catch (error) {
            setError(
                (error as { status?: number }).status === 503
                    ? "Live listener capacity is full. Try again when another listener stops."
                    : "Unable to start live audio.",
            );
        }
    }
    function stop() {
        if (audio.current) {
            audio.current.pause();
            audio.current.src = "";
            audio.current.load();
        }
        setUrl(undefined);
        setExpires(undefined);
        setStatusCount(0);
    }
    async function copy() {
        if (!url) return;
        try {
            if (navigator.clipboard) await navigator.clipboard.writeText(url);
            else throw new Error("clipboard unavailable");
        } catch {
            const input = document.createElement("textarea");
            input.value = url;
            input.setAttribute("aria-label", "Player URL fallback");
            document.body.append(input);
            input.select();
            document.execCommand("copy");
            input.remove();
        }
        setError(
            "Player URL copied. Clipboard fallback is used when browser permission is unavailable.",
        );
    }
    const minutes = expires ? Math.max(0, Math.ceil((expires * 1000 - Date.now()) / 60000)) : 0;
    const enabled = source.live_stream_enabled === true;
    return (
        <div className="live-player">
            <button type="button" onClick={url ? stop : () => void start()} disabled={!enabled}>
                {url ? "Stop live" : "Listen live"}
            </button>
            <span role="status">
                {count ?? 0} listener{count === 1 ? "" : "s"}
            </span>
            {!enabled && <span>Live streaming is disabled for this source.</span>}
            {url && (
                <>
                    <audio
                        ref={audio}
                        controls
                        aria-label={`Live audio for ${source.name ?? source.id}`}
                    />
                    <button type="button" className="secondary" onClick={() => void copy()}>
                        Copy player URL
                    </button>
                    <span>
                        Expires {new Date((expires ?? 0) * 1000).toLocaleString()} (in {minutes}{" "}
                        min)
                    </span>
                </>
            )}
            {error && (
                <span role="alert" className="error">
                    {error}
                </span>
            )}
        </div>
    );
}

function NumberField({
    name,
    label,
    value,
    min,
    max,
    step,
    onChange,
}: {
    name: string;
    label: string;
    value: number;
    min: number;
    max: number;
    step?: number;
    onChange: (value: number) => void;
}) {
    return (
        <label htmlFor={`${name}-field`}>
            {label}
            <input
                id={`${name}-field`}
                name={name}
                type="number"
                value={value}
                min={min}
                max={max}
                step={step ?? 1}
                onChange={(event) => onChange(Number(event.target.value))}
            />
        </label>
    );
}

export function SquelchEditor({
    source,
    onSaved,
    message,
}: {
    source: Source;
    onSaved: (source: Source) => void;
    message: WsMessage | undefined;
}) {
    const initial = { ...defaults, ...source.squelch };
    const [config, setConfig] = useState<SquelchConfig>(initial);
    const [error, setError] = useState("");
    const [calibrating, setCalibrating] = useState(false);
    const level = message;
    const live = level?.data?.source_id === source.id ? level.data : undefined;
    const update = (key: keyof SquelchConfig, value: number | SquelchConfig["mode"]) =>
        setConfig((current) => ({ ...current, [key]: value }));
    async function save(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setError("");
        if (config.close_dbfs > config.open_dbfs) {
            setError("close_dbfs must be less than or equal to open_dbfs");
            return;
        }
        try {
            const result = await request<Source>(`sources/${encodeURIComponent(source.id)}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ ...source, squelch: config }),
            });
            onSaved(result);
        } catch (error) {
            setError(errorText(error));
        }
    }
    async function calibrate() {
        setError("");
        setCalibrating(true);
        try {
            const result = await request<{ suggested?: { open_dbfs: number; close_dbfs: number } }>(
                `sources/${encodeURIComponent(source.id)}/squelch/calibrate`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ seconds: 10 }),
                },
            );
            if (result.suggested)
                setConfig((current) => ({
                    ...current,
                    open_dbfs: result.suggested?.open_dbfs ?? current.open_dbfs,
                    close_dbfs: result.suggested?.close_dbfs ?? current.close_dbfs,
                    mode: "level",
                }));
        } catch (error) {
            const status = (error as { status?: number }).status;
            setError(
                status === 409
                    ? "Source is not running."
                    : status === 429
                      ? "Calibration is already running."
                      : errorText(error),
            );
        } finally {
            setCalibrating(false);
        }
    }
    const mode = config.mode;
    const db = Number(live?.squelch_level_dbfs ?? live?.rms_dbfs ?? -120);
    const open = live?.open_dbfs_effective ?? source.open_dbfs_effective;
    const close = live?.close_dbfs_effective ?? source.close_dbfs_effective;
    const openState = live?.squelch_open ?? source.squelch_open;
    const position = (value: number) =>
        `${Math.max(0, Math.min(100, ((value + 120) / 120) * 100))}%`;
    return (
        <form className="squelch form" onSubmit={(event) => void save(event)}>
            <h3>Squelch</h3>
            <span role="status">{db.toFixed(0)} dBFS</span>
            <label htmlFor={`mode-${source.id}`}>
                Mode
                <select
                    id={`mode-${source.id}`}
                    aria-label="Mode"
                    value={mode}
                    onChange={(event) =>
                        update("mode", event.target.value as SquelchConfig["mode"])
                    }
                >
                    <option value="off">off</option>
                    <option value="level">level</option>
                    <option value="noise_floor">noise_floor</option>
                    <option value="auto">auto</option>
                </select>
            </label>
            {mode !== "off" && (
                <>
                    {(mode === "level" || mode === "noise_floor") && (
                        <>
                            <NumberField
                                name="open_dbfs"
                                label="Open dBFS"
                                value={config.open_dbfs}
                                min={-120}
                                max={0}
                                onChange={(v) => update("open_dbfs", v)}
                            />
                            <NumberField
                                name="close_dbfs"
                                label="Close dBFS"
                                value={config.close_dbfs}
                                min={-120}
                                max={0}
                                onChange={(v) => update("close_dbfs", v)}
                            />
                            <NumberField
                                name="attack_ms"
                                label="Attack (ms)"
                                value={config.attack_ms}
                                min={0}
                                max={2000}
                                onChange={(v) => update("attack_ms", v)}
                            />
                            <NumberField
                                name="hang_ms"
                                label="Hang (ms)"
                                value={config.hang_ms}
                                min={0}
                                max={30000}
                                onChange={(v) => update("hang_ms", v)}
                            />
                        </>
                    )}
                    {mode === "noise_floor" && (
                        <NumberField
                            name="floor_margin_db"
                            label="Floor margin (dB)"
                            value={config.floor_margin_db}
                            min={1}
                            max={40}
                            onChange={(v) => update("floor_margin_db", v)}
                        />
                    )}
                    {mode === "auto" && (
                        <>
                            <NumberField
                                name="auto_window_s"
                                label="Auto window (s)"
                                value={config.auto_window_s}
                                min={30}
                                max={1800}
                                onChange={(v) => update("auto_window_s", v)}
                            />
                            <NumberField
                                name="auto_min_samples_s"
                                label="Minimum samples (s)"
                                value={config.auto_min_samples_s}
                                min={5}
                                max={300}
                                onChange={(v) => update("auto_min_samples_s", v)}
                            />
                            <NumberField
                                name="auto_k"
                                label="Auto k"
                                value={config.auto_k}
                                min={0.25}
                                max={4}
                                step={0.1}
                                onChange={(v) => update("auto_k", v)}
                            />
                            <NumberField
                                name="min_margin_db"
                                label="Minimum margin (dB)"
                                value={config.min_margin_db}
                                min={1}
                                max={40}
                                onChange={(v) => update("min_margin_db", v)}
                            />
                            <NumberField
                                name="max_margin_db"
                                label="Maximum margin (dB)"
                                value={config.max_margin_db}
                                min={1}
                                max={60}
                                onChange={(v) => update("max_margin_db", v)}
                            />
                            <NumberField
                                name="stuck_open_s"
                                label="Stuck open (s)"
                                value={config.stuck_open_s}
                                min={30}
                                max={7200}
                                onChange={(v) => update("stuck_open_s", v)}
                            />
                            <NumberField
                                name="max_transitions_per_min"
                                label="Max transitions/min"
                                value={config.max_transitions_per_min}
                                min={2}
                                max={600}
                                onChange={(v) => update("max_transitions_per_min", v)}
                            />
                        </>
                    )}
                    <button
                        type="button"
                        className="secondary"
                        onClick={() => void calibrate()}
                        disabled={calibrating}
                    >
                        {calibrating ? "Calibrating…" : "Set from noise floor"}
                    </button>
                    {calibrating && <progress aria-label="Squelch calibration progress" />}
                    <div
                        className="level-meter"
                        role="img"
                        aria-label={`Squelch meter: ${db.toFixed(1)} dBFS, ${openState === true ? "open" : openState === false ? "closed" : "unknown"}`}
                    >
                        <span>{db.toFixed(1)} dBFS</span>
                        {open !== null && open !== undefined && (
                            <i
                                className="meter-line open-line"
                                style={{ left: position(Number(open)) }}
                                aria-hidden="true"
                            />
                        )}
                        {close !== null && close !== undefined && (
                            <i
                                className="meter-line close-line"
                                style={{ left: position(Number(close)) }}
                                aria-hidden="true"
                            />
                        )}
                        <strong>
                            {openState === true
                                ? "open"
                                : openState === false
                                  ? "closed"
                                  : "disabled"}
                        </strong>
                    </div>
                </>
            )}
            <button type="submit">Save squelch</button>
            {error && (
                <p role="alert" className="error">
                    {error}
                </p>
            )}
        </form>
    );
}

export function Diagnostics({ source }: { source: Source }) {
    const badges: Array<[keyof Source, string, string]> = [
        ["calibrating", "calibrating", "The estimator is collecting its minimum sample span."],
        ["stuck_open", "stuck open", "The carrier has remained open too long."],
        ["chatter", "chatter", "The source is transitioning more often than configured."],
    ];
    return (
        <div className="diagnostics">
            <span>Mode: {source.squelch_mode_effective ?? "—"}</span>
            <span>Open: {source.open_dbfs_effective ?? "—"} dBFS</span>
            <span>Close: {source.close_dbfs_effective ?? "—"} dBFS</span>
            <span>Floor: {source.noise_floor_dbfs ?? "—"} dBFS</span>
            <span>Transitions/min: {source.transitions_per_min ?? "—"}</span>
            {badges.map(
                ([key, label, tip]) =>
                    source[key] !== null &&
                    source[key] !== undefined && (
                        <span key={label} title={tip} role="status">
                            {label}: {source[key] ? "yes" : "no"}
                        </span>
                    ),
            )}
        </div>
    );
}
