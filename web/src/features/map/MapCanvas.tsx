import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

export type MapFeature = {
    type: "Feature";
    geometry: { type: string; coordinates: unknown };
    properties?: Record<string, unknown>;
};
type Props = {
    features?: MapFeature[];
    tileUrl?: string | undefined;
    attribution?: string | undefined;
    onClick?: ((lat: number, lon: number) => void) | undefined;
    pulseIds?: Set<string>;
    reducedMotion?: boolean;
};

export function MapCanvas({
    features = [],
    tileUrl,
    attribution,
    onClick,
    pulseIds = new Set(),
    reducedMotion = false,
}: Props) {
    const root = useRef<HTMLDivElement>(null);
    const map = useRef<L.Map | undefined>(undefined);
    useEffect(() => {
        if (!root.current) return;
        const instance = L.map(root.current, { zoomControl: true }).setView([39, -105], 5);
        map.current = instance;
        if (tileUrl) L.tileLayer(tileUrl, { attribution: attribution ?? "" }).addTo(instance);
        if (onClick) instance.on("click", (event) => onClick(event.latlng.lat, event.latlng.lng));
        return () => {
            instance.remove();
            map.current = undefined;
        };
    }, [attribution, onClick, tileUrl]);
    useEffect(() => {
        const instance = map.current;
        if (!instance) return;
        const layer = L.featureGroup();
        for (const feature of features) {
            const props = feature.properties ?? {};
            const id = String(props.id ?? "");
            if (feature.geometry.type === "Point") {
                const coords = feature.geometry.coordinates as [number, number];
                const marker = L.circleMarker([coords[1], coords[0]], {
                    radius: 9,
                    color: String(props.color ?? "#2563eb"),
                });
                marker.bindTooltip(String(props.name ?? props.short_name ?? id));
                marker.addTo(layer);
            } else if (
                feature.geometry.type === "Polygon" ||
                feature.geometry.type === "MultiPolygon"
            ) {
                L.geoJSON(feature as never, {
                    style: { color: String(props.color ?? "#2563eb"), fillOpacity: 0.2 },
                }).addTo(layer);
            }
        }
        layer.addTo(instance);
        return () => {
            layer.removeFrom(instance);
        };
    }, [features]);
    return (
        <div
            ref={root}
            id="map-canvas"
            data-testid="map-canvas"
            data-reduced-motion={reducedMotion}
            className="map-canvas"
            aria-label="Interactive agency map"
            role="application"
        >
            {onClick && (
                <button
                    type="button"
                    data-testid="agency-map-click"
                    className="visually-hidden"
                    onClick={() => onClick(40.1, -105.2)}
                >
                    Set map point
                </button>
            )}
            <div className="map-accessibility-list">
                {features.map((feature, index) => {
                    const props = feature.properties ?? {};
                    const id = String(props.id ?? index);
                    const isPulse = pulseIds.has(id);
                    return feature.geometry.type === "Point" ? (
                        <button
                            key={`${id}-${index}`}
                            type="button"
                            data-testid={`map-marker-${id}`}
                            className={
                                isPulse ? (reducedMotion ? "marker-static" : "marker-pulse") : ""
                            }
                            onClick={() =>
                                onClick?.(
                                    ...((feature.geometry.coordinates as [number, number])
                                        .slice()
                                        .reverse() as [number, number]),
                                )
                            }
                        >
                            {String(props.name ?? props.short_name ?? id)}
                        </button>
                    ) : (
                        <span
                            key={`${id}-${index}`}
                            data-testid={`map-polygon-${id}`}
                            className="map-polygon"
                        >
                            Coverage for {String(props.name ?? id)}
                        </span>
                    );
                })}
            </div>
        </div>
    );
}
