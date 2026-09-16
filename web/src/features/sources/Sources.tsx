import { FormEvent, useEffect, useState } from "react";
import { request } from "../../api/client";
import { useSubscription } from "../../lib/ws";
import { Diagnostics, LivePlayer, Source, SquelchEditor } from "./SourceControls";

const sourceTopics = ["levels", "events"];

export function Sources() {
    const [items, setItems] = useState<Source[]>([]);
    const [devices, setDevices] = useState<{ name?: string; index?: number }[]>([]);
    const [type, setType] = useState("soundcard");
    const [error, setError] = useState("");
    const message = useSubscription(sourceTopics);
    const events = message;
    const levelMessage =
        message?.type === "LevelUpdate" || message?.type === "ChannelLevel" ? message : undefined;
    const reload = () =>
        request<Source[]>("sources")
            .then(setItems)
            .catch(() => undefined);
    useEffect(() => {
        void reload();
        request<typeof devices>("devices")
            .then(setDevices)
            .catch(() => undefined);
    }, []);
    useEffect(() => {
        if (events?.type !== "live_listeners_changed") return;
        const sourceId = String(events.data?.source_id ?? "");
        const listeners = Number(events.data?.source_listeners ?? 0);
        setItems((current) =>
            current.map((source) =>
                source.id === sourceId ? { ...source, live_listeners: listeners } : source,
            ),
        );
    }, [events]);
    async function save(e: FormEvent<HTMLFormElement>) {
        e.preventDefault();
        setError("");
        const f = new FormData(e.currentTarget);
        const url = String(f.get("url") || "");
        if (type === "stream" && !/^https?:\/\//i.test(url) && !/^rtsp?:\/\//i.test(url)) {
            setError("Use an http(s) or rtsp(s) URL; the server validates this too.");
            return;
        }
        const body: Source = {
            id: String(f.get("id") || crypto.randomUUID()),
            name: String(f.get("name") || "Source"),
            type,
        };
        if (type === "soundcard") {
            body.device = String(f.get("device") || "");
            body.channel = Number(f.get("channel") || 0);
        }
        if (type === "stream") body.url = url;
        if (type === "file") body.path = String(f.get("path") || "");
        if (type === "rtlsdr") {
            body.frequency_hz = Number(f.get("frequency") || 0) * 1e6;
            body.gain = Number(f.get("gain") || 0);
            body.ppm = Number(f.get("ppm") || 0);
            body.rtl_fm_squelch = Number(f.get("squelch") || 0);
        }
        try {
            await request("sources", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            void reload();
        } catch (e) {
            setError(
                (
                    e as { body?: { detail?: { loc?: (string | number)[]; msg?: string }[] } }
                ).body?.detail
                    ?.map((x) => `${x.loc?.join(".")}: ${x.msg}`)
                    .join("; ") ?? "Unable to save source",
            );
        }
    }
    return (
        <>
            <h1>Sources</h1>
            {items.map((source) => {
                const live =
                    levelMessage?.data?.source_id === source.id
                        ? {
                              ...source,
                              open_dbfs_effective: levelMessage.data.open_dbfs_effective as
                                  number | null,
                              close_dbfs_effective: levelMessage.data.close_dbfs_effective as
                                  number | null,
                              noise_floor_dbfs: levelMessage.data.noise_floor_dbfs as number | null,
                              squelch_open: levelMessage.data.squelch_open as boolean | null,
                              transitions_per_min: levelMessage.data.transitions_per_min as
                                  number | null,
                              calibrating: levelMessage.data.calibrating as boolean | null,
                              stuck_open: levelMessage.data.stuck_open as boolean | null,
                              chatter: levelMessage.data.chatter as boolean | null,
                              squelch_mode_effective: levelMessage.data.squelch_mode_effective as
                                  string | null,
                          }
                        : source;
                return (
                    <section className="card" key={source.id}>
                        <h2>{source.name ?? source.id}</h2>
                        <p>
                            {source.id} · {source.type}{" "}
                            {levelMessage?.data?.source_id === source.id && (
                                <span>{`${String(levelMessage.data.dbfs ?? levelMessage.data.rms_dbfs ?? "")} dBFS`}</span>
                            )}
                        </p>
                        <LivePlayer source={source} message={message} />
                        <Diagnostics source={live} />
                        <SquelchEditor
                            source={source}
                            message={message}
                            onSaved={(updated) =>
                                setItems((current) =>
                                    current.map((item) =>
                                        item.id === updated.id ? updated : item,
                                    ),
                                )
                            }
                        />
                    </section>
                );
            })}
            <form className="form" onSubmit={save}>
                <h2>Add source</h2>
                <label htmlFor="id">
                    ID
                    <input id="id" name="id" />
                </label>
                <label htmlFor="name">
                    Name
                    <input id="name" name="name" required />
                </label>
                <label htmlFor="source-type">
                    Type
                    <select id="source-type" value={type} onChange={(e) => setType(e.target.value)}>
                        <option>soundcard</option>
                        <option>stream</option>
                        <option>rtlsdr</option>
                        <option>file</option>
                    </select>
                </label>
                {type === "soundcard" && (
                    <>
                        <label htmlFor="device">
                            Device
                            <select id="device" name="device">
                                {devices.map((d, i) => (
                                    <option key={i}>{d.name ?? String(d.index)}</option>
                                ))}
                            </select>
                        </label>
                        <label htmlFor="channel">
                            Channel
                            <input id="channel" name="channel" type="number" defaultValue="0" />
                        </label>
                    </>
                )}
                {type === "stream" && (
                    <label htmlFor="url">
                        Stream URL
                        <input id="url" name="url" />
                    </label>
                )}
                {type === "file" && (
                    <label htmlFor="path">
                        File path
                        <input id="path" name="path" />
                    </label>
                )}
                {type === "rtlsdr" && (
                    <>
                        <label htmlFor="frequency">
                            Frequency (MHz)
                            <input id="frequency" name="frequency" type="number" step="any" />
                        </label>
                        <label htmlFor="gain">
                            Gain
                            <input id="gain" name="gain" type="number" />
                        </label>
                        <label htmlFor="ppm">
                            PPM
                            <input id="ppm" name="ppm" type="number" />
                        </label>
                        <label htmlFor="squelch">
                            Hardware squelch
                            <input id="squelch" name="squelch" type="number" />
                        </label>
                    </>
                )}
                <button type="submit">Save source</button>
                {error && (
                    <p role="alert" className="error">
                        {error}
                    </p>
                )}
            </form>
        </>
    );
}
