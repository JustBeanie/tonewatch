import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { request } from "../../api/client";
import { useWsEvents, WsMessage } from "../../lib/ws";
import { MapCanvas, MapFeature } from "./MapCanvas";
type Config = { map?: { tile_url?: string; attribution?: string } };
type Call = { id: string; started_at: string; status: string };
type ToneSet = { id: string; name: string; agency_id?: string | null };
type ActiveCall = { agencyId: string; expiresAt: number; closed: boolean };
export const MINIMUM_PULSE_MS = 8000;
export function MapPage() {
    const [features, setFeatures] = useState<MapFeature[]>([]);
    const [config, setConfig] = useState<Config>();
    const [calls, setCalls] = useState<Call[]>([]);
    const [toneSets, setToneSets] = useState<ToneSet[]>([]);
    const [selected, setSelected] = useState<string>();
    const [pulse, setPulse] = useState(new Set<string>());
    const activeCalls = useRef(new Map<string, ActiveCall>());
    const pulseTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
    const [reduced, setReduced] = useState(false);
    const processEvent = (event: WsMessage) => {
        const scheduleExpiry = (agencyId: string) => {
            const records = [...activeCalls.current.values()].filter(
                (call) => call.agencyId === agencyId,
            );
            const earliest = records
                .filter((call) => call.closed)
                .reduce<number | undefined>(
                    (value, call) => Math.min(value ?? call.expiresAt, call.expiresAt),
                    undefined,
                );
            const existing = pulseTimers.current.get(agencyId);
            if (existing) clearTimeout(existing);
            if (earliest === undefined) {
                pulseTimers.current.delete(agencyId);
                return;
            }
            const timer = setTimeout(
                () => {
                    pulseTimers.current.delete(agencyId);
                    const now = Date.now();
                    for (const [callId, call] of activeCalls.current) {
                        if (call.agencyId === agencyId && call.closed && call.expiresAt <= now)
                            activeCalls.current.delete(callId);
                    }
                    const remaining = [...activeCalls.current.values()].filter(
                        (call) => call.agencyId === agencyId,
                    );
                    if (!remaining.some((call) => !call.closed) && remaining.length === 0) {
                        setPulse((old) => {
                            const next = new Set(old);
                            next.delete(agencyId);
                            return next;
                        });
                    } else if (remaining.some((call) => call.closed)) scheduleExpiry(agencyId);
                },
                Math.max(0, earliest - Date.now()),
            );
            pulseTimers.current.set(agencyId, timer);
        };
        const data = event.data ?? {};
        const agency = data.agency as { id?: string } | undefined;
        const tonesetAgency = toneSets.find((tone) => tone.id === data.toneset_id)?.agency_id;
        const eventAgencyId = agency?.id ?? tonesetAgency;
        const callId = String(data.call_id ?? "");
        if (event.type === "ToneDetected" && eventAgencyId && callId) {
            activeCalls.current.set(callId, {
                agencyId: eventAgencyId,
                expiresAt: Date.now() + MINIMUM_PULSE_MS,
                closed: false,
            });
            setPulse((old) => new Set(old).add(eventAgencyId));
            scheduleExpiry(eventAgencyId);
        }
        if (event.type === "CallClosed" && callId) {
            const call = activeCalls.current.get(callId);
            if (call) {
                call.closed = true;
                if (call.expiresAt <= Date.now()) {
                    activeCalls.current.delete(callId);
                    if (
                        ![...activeCalls.current.values()].some(
                            (item) => item.agencyId === call.agencyId && !item.closed,
                        ) &&
                        ![...activeCalls.current.values()].some(
                            (item) => item.agencyId === call.agencyId,
                        )
                    )
                        setPulse((old) => {
                            const next = new Set(old);
                            next.delete(call.agencyId);
                            return next;
                        });
                } else scheduleExpiry(call.agencyId);
            }
        }
    };
    useWsEvents("events", processEvent);
    useEffect(() => {
        request<{ features: MapFeature[] }>("agencies.geojson")
            .then((v) => setFeatures(v.features))
            .catch(() => undefined);
        request<Config>("map-config")
            .then(setConfig)
            .catch(() => undefined);
        request<ToneSet[]>("tonesets")
            .then((value) => {
                if (Array.isArray(value)) setToneSets(value);
            })
            .catch(() => undefined);
        setReduced(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
    }, []);
    useEffect(
        () => () => {
            for (const timer of pulseTimers.current.values()) clearTimeout(timer);
            pulseTimers.current.clear();
            activeCalls.current.clear();
        },
        [],
    );
    const agency = useMemo(
        () => features.find((f) => String(f.properties?.id) === selected)?.properties,
        [features, selected],
    );
    useEffect(() => {
        if (selected)
            request<{ items: Call[] }>(`calls?agency_id=${encodeURIComponent(selected)}&limit=5`)
                .then((v) => setCalls(v.items))
                .catch(() => undefined);
    }, [selected]);
    return (
        <>
            <h1>Agency map</h1>
            {!config?.map?.tile_url && (
                <p className="card">
                    Tiles are disabled. Configure a tile URL in <Link to="/settings">Settings</Link>
                    .
                </p>
            )}
            <MapCanvas
                features={features}
                tileUrl={config?.map?.tile_url}
                attribution={config?.map?.attribution}
                pulseIds={pulse}
                reducedMotion={reduced}
            />{" "}
            <section className="card" aria-label="Agency list">
                <h2>Agencies</h2>
                {[...new Set(features.map((f) => String(f.properties?.id ?? "")))]
                    .filter(Boolean)
                    .map((id) => (
                        <button type="button" key={id} onClick={() => setSelected(id)}>
                            {String(
                                features.find((f) => String(f.properties?.id) === id)?.properties
                                    ?.name ?? id,
                            )}
                        </button>
                    ))}
            </section>
            {agency && (
                <section className="card">
                    <h2>{String(agency.name)}</h2>
                    <p>{String(agency.kind)}</p>
                    <h3>Tone sets</h3>
                    <p>
                        {toneSets
                            .filter((tone) => tone.agency_id === selected)
                            .map((tone) => tone.name)
                            .join(", ") || "None linked"}
                    </p>
                    <h3>Last 5 calls</h3>
                    {calls.map((call) => (
                        <p key={call.id}>
                            <Link to={`/calls/${call.id}`}>
                                {call.started_at} · {call.status}
                            </Link>
                        </p>
                    ))}
                </section>
            )}
        </>
    );
}
