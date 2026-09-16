import { useEffect, useMemo, useState } from "react";
import { request } from "../../api/client";
import { MeshtasticFields } from "./MeshtasticFields";
import {
    errorText,
    initialMesh,
    type MeshForm,
    useMeshtasticPreview,
} from "./useMeshtasticPreview";

export type Target = { id: string; name?: string; type: string; secret_set?: boolean };
export function Alerts() {
    const [items, setItems] = useState<Target[]>([]);
    const [type, setType] = useState("mqtt");
    const [name, setName] = useState("");
    const [mesh, setMesh] = useState<MeshForm>(initialMesh);
    const [secret, setSecret] = useState("");
    const [url, setUrl] = useState("");
    const [error, setError] = useState("");
    const [previewDirty, setPreviewDirty] = useState(false);
    const [testResults, setTestResults] = useState<Record<string, string>>({});
    useEffect(() => {
        request<Target[]>("alert-targets")
            .then(setItems)
            .catch(() => undefined);
    }, []);
    const mqttTargets = useMemo(() => items.filter((item) => item.type === "mqtt"), [items]);
    const { preview, previewError } = useMeshtasticPreview(mesh, name, type, previewDirty);
    function updateMesh<K extends keyof MeshForm>(key: K, value: MeshForm[K]) {
        setMesh((current) => ({ ...current, [key]: value }));
        setPreviewDirty(true);
    }
    async function sendTest(id: string) {
        try {
            const result = await request<{ ok: boolean; error?: string }>(
                `alert-targets/${id}/test`,
                { method: "POST" },
            );
            setTestResults((current) => ({
                ...current,
                [id]: result.ok ? "Test sent" : result.error || "Test failed",
            }));
        } catch (value) {
            setTestResults((current) => ({ ...current, [id]: errorText(value) }));
        }
    }
    async function save(event: React.FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setError("");
        const id = crypto.randomUUID();
        const base = { id, name, type, enabled: true };
        const body =
            type === "meshtastic"
                ? {
                      ...base,
                      transport: "mqtt",
                      ...mesh,
                      host: mesh.mqtt_target_id ? null : mesh.host || null,
                      mqtt_target_id: mesh.mqtt_target_id || null,
                      username: mesh.username || null,
                      password: mesh.password || null,
                      timezone: mesh.timezone || null,
                  }
                : type === "webhook"
                  ? { ...base, url, secret: secret || undefined }
                  : type === "mqtt"
                    ? { ...base, broker: "localhost", password: secret || undefined }
                    : { ...base, command: ["/usr/bin/true"] };
        try {
            await request("alert-targets", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            setItems(await request<Target[]>("alert-targets"));
        } catch (value) {
            setError(
                (value as { status?: number }).status === 403
                    ? "Script targets are disabled on this server"
                    : errorText(value),
            );
        }
    }
    const publicChannelUnacknowledged =
        type === "meshtastic" && mesh.channel_index === 0 && !mesh.acknowledge_public_channel;
    return (
        <>
            <h1>Alerts</h1>
            {items.map((item) => (
                <div className="card" key={item.id}>
                    <b>{item.name ?? item.id}</b> · {item.type}
                    {item.type === "webhook" && (
                        <span>
                            {" "}
                            — {item.secret_set ? "secret set" : "no secret"}; secrets are
                            write-only.
                        </span>
                    )}
                    {item.type === "script" && (
                        <p role="alert">
                            <strong>Warning: scripts execute on the server.</strong>
                        </p>
                    )}
                    <button type="button" onClick={() => void sendTest(item.id)}>
                        Send test
                    </button>
                    {testResults[item.id] && <span role="status"> {testResults[item.id]}</span>}
                </div>
            ))}
            <form className="form" onSubmit={save}>
                <label htmlFor="alert-name">
                    Name
                    <input
                        id="alert-name"
                        name="name"
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        required
                    />
                </label>
                <label htmlFor="alert-type">
                    Type
                    <select
                        id="alert-type"
                        name="type"
                        value={type}
                        onChange={(event) => {
                            setType(event.target.value);
                            setPreviewDirty(false);
                        }}
                    >
                        <option value="mqtt">mqtt</option>
                        <option value="webhook">webhook</option>
                        <option value="script">script</option>
                        <option value="meshtastic">meshtastic</option>
                    </select>
                </label>
                {type === "webhook" && (
                    <label htmlFor="alert-url">
                        URL
                        <input
                            id="alert-url"
                            value={url}
                            onChange={(event) => setUrl(event.target.value)}
                            required
                        />
                    </label>
                )}
                {(type === "mqtt" || type === "webhook") && (
                    <label htmlFor="secret">
                        Secret (write-only)
                        <input
                            id="secret"
                            name="secret"
                            type="password"
                            autoComplete="new-password"
                            value={secret}
                            onChange={(event) => setSecret(event.target.value)}
                        />
                    </label>
                )}
                {type === "meshtastic" && (
                    <MeshtasticFields
                        mesh={mesh}
                        mqttTargets={mqttTargets}
                        updateMesh={updateMesh}
                        preview={preview}
                        previewError={previewError}
                    />
                )}
                <button disabled={publicChannelUnacknowledged}>Save target</button>
                {error && (
                    <p role="alert" className="error">
                        {error}
                    </p>
                )}
            </form>
        </>
    );
}
