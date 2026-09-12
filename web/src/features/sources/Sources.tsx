import { FormEvent, useEffect, useState } from "react";
import { request } from "../../api/client";
import { useSubscription } from "../../lib/ws";
type Source = {
    id: string;
    name?: string;
    type: string;
    device?: string;
    channel?: number;
    url?: string;
    frequency_hz?: number;
    gain?: number;
    ppm?: number;
    squelch?: number;
};
export function Sources() {
    const [items, setItems] = useState<Source[]>([]);
    const [devices, setDevices] = useState<{ name?: string; index?: number }[]>([]);
    const [type, setType] = useState("soundcard");
    const [error, setError] = useState("");
    const level = useSubscription("levels");
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
        if (type === "rtlsdr") {
            body.frequency_hz = Number(f.get("frequency") || 0) * 1e6;
            body.gain = Number(f.get("gain") || 0);
            body.ppm = Number(f.get("ppm") || 0);
            body.squelch = Number(f.get("squelch") || 0);
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
            {items.map((i) => (
                <div className="card" key={i.id}>
                    {i.name ?? i.id} · {i.type}{" "}
                    {i.id === String(level?.data?.source_id) && (
                        <span role="status">{String(level?.data?.dbfs)} dBFS</span>
                    )}
                </div>
            ))}
            <form className="form" onSubmit={save}>
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
                        <input id="url" name="url" type="text" />
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
                            Squelch
                            <input id="squelch" name="squelch" type="number" />
                        </label>
                    </>
                )}
                <button>Save source</button>
                {error && (
                    <p role="alert" className="error">
                        {error}
                    </p>
                )}
            </form>
        </>
    );
}
