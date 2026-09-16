import { useEffect, useState } from "react";
import { request } from "../../api/client";

export type Preview = { text: string; bytes: number; max_bytes: number; truncated: boolean };
export type MeshForm = {
    host: string;
    port: number;
    tls: boolean;
    username: string;
    password: string;
    mqtt_target_id: string;
    root_topic: string;
    gateway_node_id: string;
    channel_index: number;
    destination: string;
    template: string;
    max_bytes: number;
    phases: string[];
    min_interval_s: number;
    max_per_hour: number;
    timezone: string;
    acknowledge_public_channel: boolean;
};
export const initialMesh: MeshForm = {
    host: "",
    port: 1883,
    tls: false,
    username: "",
    password: "",
    mqtt_target_id: "",
    root_topic: "msh/US",
    gateway_node_id: "!9abc1234",
    channel_index: 0,
    destination: "broadcast",
    template: "TONE {agency_short} {toneset} {time}",
    max_bytes: 200,
    phases: ["pre_alert"],
    min_interval_s: 30,
    max_per_hour: 20,
    timezone: "",
    acknowledge_public_channel: false,
};
export function errorText(error: unknown): string {
    const body = (error as { body?: { detail?: unknown } })?.body?.detail;
    if (typeof body === "string") return body;
    if (body !== undefined) return JSON.stringify(body);
    return "Unable to save target";
}
export function useMeshtasticPreview(mesh: MeshForm, name: string, type: string, dirty: boolean) {
    const [preview, setPreview] = useState<Preview | null>(null);
    const [previewError, setPreviewError] = useState("");
    useEffect(() => {
        if (type !== "meshtastic" || !dirty) return undefined;
        const timer = window.setTimeout(() => {
            const payload = {
                id: "preview",
                name: name || "Preview",
                type: "meshtastic",
                ...mesh,
                host: mesh.mqtt_target_id ? null : mesh.host || null,
                mqtt_target_id: mesh.mqtt_target_id || null,
                username: mesh.username || null,
                password: mesh.password || null,
                timezone: mesh.timezone || null,
            };
            request<Preview>("alert-targets/meshtastic/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            })
                .then((value) => {
                    setPreview(value);
                    setPreviewError("");
                })
                .catch((value: unknown) => {
                    setPreview(null);
                    setPreviewError(errorText(value));
                });
        }, 300);
        return () => window.clearTimeout(timer);
    }, [mesh, name, dirty, type]);
    return { preview, previewError };
}
