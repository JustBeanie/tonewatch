import type { Target } from "./Alerts";
import type { MeshForm, Preview } from "./useMeshtasticPreview";

type Props = {
    mesh: MeshForm;
    mqttTargets: Target[];
    updateMesh: <K extends keyof MeshForm>(key: K, value: MeshForm[K]) => void;
    preview: Preview | null;
    previewError: string;
};
export function MeshtasticFields({ mesh, mqttTargets, updateMesh, preview, previewError }: Props) {
    return (
        <>
            <p>
                Mesh messages are readable by anyone with the channel key. URLs never go on the
                mesh.
            </p>
            <label htmlFor="mesh-host">
                Broker host
                <input
                    id="mesh-host"
                    value={mesh.host}
                    disabled={Boolean(mesh.mqtt_target_id)}
                    onChange={(event) => updateMesh("host", event.target.value)}
                />
            </label>
            <label htmlFor="mesh-port">
                Broker port
                <input
                    id="mesh-port"
                    type="number"
                    value={mesh.port}
                    onChange={(event) => updateMesh("port", Number(event.target.value))}
                />
            </label>
            <label>
                <input
                    type="checkbox"
                    checked={mesh.tls}
                    onChange={(event) => updateMesh("tls", event.target.checked)}
                />{" "}
                TLS
            </label>
            <label htmlFor="mesh-username">
                Username
                <input
                    id="mesh-username"
                    value={mesh.username}
                    onChange={(event) => updateMesh("username", event.target.value)}
                />
            </label>
            <label htmlFor="mesh-password">
                Password (write-only)
                <input
                    id="mesh-password"
                    type="password"
                    autoComplete="new-password"
                    value={mesh.password}
                    onChange={(event) => updateMesh("password", event.target.value)}
                />
            </label>
            <label htmlFor="mesh-mqtt-target">
                Existing MQTT target
                <select
                    id="mesh-mqtt-target"
                    value={mesh.mqtt_target_id}
                    onChange={(event) => updateMesh("mqtt_target_id", event.target.value)}
                >
                    <option value="">Inline broker</option>
                    {mqttTargets.map((item) => (
                        <option key={item.id} value={item.id}>
                            {item.name ?? item.id}
                        </option>
                    ))}
                </select>
            </label>
            <label htmlFor="mesh-root">
                Root topic
                <input
                    id="mesh-root"
                    value={mesh.root_topic}
                    onChange={(event) => updateMesh("root_topic", event.target.value)}
                    required
                />
            </label>
            <label htmlFor="mesh-gateway">
                Gateway node ID
                <input
                    id="mesh-gateway"
                    value={mesh.gateway_node_id}
                    onChange={(event) => updateMesh("gateway_node_id", event.target.value)}
                    required
                />
            </label>
            <label htmlFor="mesh-channel">
                Channel index
                <input
                    id="mesh-channel"
                    type="number"
                    min={0}
                    max={7}
                    value={mesh.channel_index}
                    onChange={(event) => updateMesh("channel_index", Number(event.target.value))}
                />
            </label>
            {mesh.channel_index === 0 && (
                <label>
                    <input
                        type="checkbox"
                        checked={mesh.acknowledge_public_channel}
                        onChange={(event) =>
                            updateMesh("acknowledge_public_channel", event.target.checked)
                        }
                    />{" "}
                    I acknowledge that channel 0 is public and readable nearby.
                </label>
            )}
            <label htmlFor="mesh-destination">
                Destination
                <input
                    id="mesh-destination"
                    value={mesh.destination}
                    onChange={(event) => updateMesh("destination", event.target.value)}
                />
            </label>
            <label htmlFor="mesh-template">
                Template
                <input
                    id="mesh-template"
                    value={mesh.template}
                    onChange={(event) => updateMesh("template", event.target.value)}
                />
            </label>
            <label htmlFor="mesh-max">
                Maximum bytes
                <input
                    id="mesh-max"
                    type="number"
                    min={1}
                    max={200}
                    value={mesh.max_bytes}
                    onChange={(event) => updateMesh("max_bytes", Number(event.target.value))}
                />
            </label>
            <label htmlFor="mesh-phases">
                Phases
                <input
                    id="mesh-phases"
                    value={mesh.phases.join(",")}
                    onChange={(event) =>
                        updateMesh("phases", event.target.value.split(",").filter(Boolean))
                    }
                />
            </label>
            <label htmlFor="mesh-min">
                Minimum interval seconds
                <input
                    id="mesh-min"
                    type="number"
                    min={0}
                    value={mesh.min_interval_s}
                    onChange={(event) => updateMesh("min_interval_s", Number(event.target.value))}
                />
            </label>
            <label htmlFor="mesh-hour">
                Maximum per hour
                <input
                    id="mesh-hour"
                    type="number"
                    min={1}
                    value={mesh.max_per_hour}
                    onChange={(event) => updateMesh("max_per_hour", Number(event.target.value))}
                />
            </label>
            <label htmlFor="mesh-timezone">
                Timezone
                <input
                    id="mesh-timezone"
                    value={mesh.timezone}
                    onChange={(event) => updateMesh("timezone", event.target.value)}
                />
            </label>
            {preview && (
                <div role="status">
                    <code>{preview.text}</code>
                    <p>
                        {preview.bytes} / {preview.max_bytes} bytes
                    </p>
                    {preview.truncated && (
                        <p role="alert">Message truncated to fit the byte limit.</p>
                    )}
                </div>
            )}
            {previewError && (
                <p role="alert" className="error">
                    Preview: {previewError}
                </p>
            )}
        </>
    );
}
