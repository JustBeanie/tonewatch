import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { request } from "../../api/client";
import { MapCanvas } from "../map/MapCanvas";
import { Incident, IncidentCard } from "../cad/Incidents";

type Agency = {
    id: string;
    name: string;
    short_name: string;
    kind: string;
    color: string;
    address: Record<string, string>;
    location: { lat: number; lon: number };
    stations: { name: string; lat: number; lon: number }[];
    coverage: Record<string, unknown> | null;
    cad_names: string[];
};
const blank: Agency = {
    id: "",
    name: "",
    short_name: "",
    kind: "fire",
    color: "#2563eb",
    address: { street: "", city: "", region: "", postal_code: "", country: "" },
    location: { lat: 0, lon: 0 },
    stations: [],
    coverage: null,
    cad_names: [],
};
type ApiError = { body?: { detail?: unknown } };

function formatDetail(detail: unknown): string {
    if (typeof detail === "string") return detail;
    if (!Array.isArray(detail)) return "";
    return detail
        .map((item) => {
            if (!item || typeof item !== "object") return String(item);
            const value = item as { loc?: unknown; msg?: unknown };
            const location = Array.isArray(value.loc)
                ? value.loc.filter((part) => part !== "body").join(".")
                : "";
            const message = typeof value.msg === "string" ? value.msg : String(value.msg ?? item);
            return location ? `${location}: ${message}` : message;
        })
        .join("; ");
}

export const errorText = (error: unknown): string => {
    const detail = formatDetail((error as ApiError)?.body?.detail);
    if (detail) return detail;
    if (error instanceof Error && error.message) return error.message;
    return "Unable to save agency.";
};

export function AgencyForm() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [agency, setAgency] = useState<Agency>({ ...blank });
    const [tags, setTags] = useState("");
    const [coverageText, setCoverageText] = useState("");
    const [mapMode, setMapMode] = useState(false);
    const [stationMode, setStationMode] = useState(false);
    const [stationName, setStationName] = useState("");
    const [error, setError] = useState("");
    const [toneSets, setToneSets] = useState<
        { id: string; name: string; agency_id?: string | null }[]
    >([]);
    const [linked, setLinked] = useState<Set<string>>(new Set());
    const [incidents, setIncidents] = useState<Incident[]>([]);
    useEffect(() => {
        request<{ id: string; name: string; agency_id?: string | null }[]>("tonesets")
            .then((value) => {
                setToneSets(value);
                setLinked(
                    new Set(value.filter((tone) => tone.agency_id === id).map((tone) => tone.id)),
                );
            })
            .catch(() => undefined);
        if (id)
            request<Agency>(`agencies/${id}`)
                .then((value) => {
                    setAgency(value);
                    return request<Incident[]>(
                        "cad/incidents?status=active&configured_only=false&limit=100",
                    ).then((items) =>
                        setIncidents(
                            items.filter(
                                (item) =>
                                    item.agency_key &&
                                    value.cad_names.some(
                                        (name) =>
                                            name.toLowerCase() === item.agency_key?.toLowerCase(),
                                    ),
                            ),
                        ),
                    );
                })
                .catch(() => undefined);
    }, [id]);
    const update = (field: keyof Agency, value: unknown) =>
        setAgency((old) => ({ ...old, [field]: value }));
    const place = (lat: number, lon: number) => {
        const point = { lat: Number(lat.toFixed(6)), lon: Number(lon.toFixed(6)) };
        if (stationMode && stationName.trim()) {
            update("stations", [...agency.stations, { name: stationName.trim(), ...point }]);
            setStationName("");
            setStationMode(false);
        } else update("location", point);
    };
    async function save(event: FormEvent) {
        event.preventDefault();
        setError("");
        let coverage = agency.coverage;
        if (coverageText.trim()) {
            try {
                coverage = JSON.parse(coverageText) as Record<string, unknown>;
            } catch {
                setError("Coverage must be valid JSON.");
                return;
            }
        }
        const payload = {
            ...agency,
            id:
                agency.id ||
                agency.name
                    .toLowerCase()
                    .replace(/[^a-z0-9]+/g, "-")
                    .replace(/^-|-$/g, ""),
            location: { lat: Number(agency.location.lat), lon: Number(agency.location.lon) },
            coverage,
            cad_names: agency.cad_names,
        };
        try {
            await request(id ? `agencies/${id}` : "agencies", {
                method: id ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            const affectedToneSets = toneSets.filter(
                (tone) => linked.has(tone.id) || tone.agency_id === payload.id,
            );
            for (const tone of affectedToneSets) {
                const detail = await request<Record<string, unknown>>(`tonesets/${tone.id}`);
                await request(`tonesets/${tone.id}`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        ...detail,
                        agency_id: linked.has(tone.id) ? payload.id : null,
                    }),
                });
            }
            navigate("/agencies");
        } catch (reason) {
            setError(errorText(reason));
        }
    }
    function addTag(event: React.KeyboardEvent<HTMLInputElement>) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        const value = tags.trim();
        if (value && !agency.cad_names.includes(value))
            update("cad_names", [...agency.cad_names, value]);
        setTags("");
    }
    function upload(event: ChangeEvent<HTMLInputElement>) {
        const file = event.target.files?.[0];
        if (!file) return;
        void file.text().then(setCoverageText);
    }
    const features = [
        {
            type: "Feature" as const,
            geometry: { type: "Point", coordinates: [agency.location.lon, agency.location.lat] },
            properties: { id: "draft", name: agency.name, color: agency.color },
        },
    ];
    return (
        <form className="form agency-editor" onSubmit={(event) => void save(event)}>
            <h1>{id ? "Edit agency" : "Create agency"}</h1>
            <label htmlFor="agency-id">
                ID
                <input
                    id="agency-id"
                    value={agency.id}
                    onChange={(e) => update("id", e.target.value)}
                    placeholder="north-unit"
                    required={!id}
                />
            </label>
            <label htmlFor="agency-name">
                Name
                <input
                    id="agency-name"
                    value={agency.name}
                    onChange={(e) => update("name", e.target.value)}
                    required
                />
            </label>
            <label htmlFor="short-name">
                Short name
                <input
                    id="short-name"
                    value={agency.short_name}
                    onChange={(e) => update("short_name", e.target.value)}
                    required
                />
            </label>
            <label htmlFor="kind">
                Kind
                <select
                    id="kind"
                    value={agency.kind}
                    onChange={(e) => update("kind", e.target.value)}
                >
                    {["fire", "ems", "police", "rescue", "dispatch", "other"].map((kind) => (
                        <option key={kind}>{kind}</option>
                    ))}
                </select>
            </label>
            {Object.keys(agency.address).map((field) => (
                <label key={field} htmlFor={`address-${field}`}>
                    {field}
                    <input
                        id={`address-${field}`}
                        value={agency.address[field]}
                        onChange={(e) =>
                            update("address", { ...agency.address, [field]: e.target.value })
                        }
                    />
                </label>
            ))}
            <label htmlFor="cad-names">
                CAD names
                <input
                    id="cad-names"
                    value={tags}
                    onChange={(e) => setTags(e.target.value)}
                    onKeyDown={addTag}
                    placeholder="Type a name and press Enter"
                />
            </label>
            <div aria-label="CAD name tags">
                {agency.cad_names.map((tag) => (
                    <button
                        type="button"
                        key={tag}
                        onClick={() =>
                            update(
                                "cad_names",
                                agency.cad_names.filter((item) => item !== tag),
                            )
                        }
                    >
                        {tag} ×
                    </button>
                ))}
            </div>
            <div className="grid">
                <label htmlFor="latitude">
                    Latitude
                    <input
                        id="latitude"
                        type="number"
                        step="any"
                        value={agency.location.lat}
                        onChange={(e) => place(Number(e.target.value), agency.location.lon)}
                    />
                </label>
                <label htmlFor="longitude">
                    Longitude
                    <input
                        id="longitude"
                        type="number"
                        step="any"
                        value={agency.location.lon}
                        onChange={(e) => place(agency.location.lat, Number(e.target.value))}
                    />
                </label>
            </div>
            <button type="button" onClick={() => setMapMode(!mapMode)}>
                Place on map
            </button>
            <label htmlFor="station-name">
                Station name
                <input
                    id="station-name"
                    value={stationName}
                    onChange={(e) => setStationName(e.target.value)}
                />
            </label>
            <button
                type="button"
                disabled={!stationName.trim()}
                onClick={() => {
                    setStationMode(true);
                    setMapMode(true);
                }}
            >
                Add station at map click
            </button>
            {agency.stations.map((station) => (
                <p key={`${station.name}-${station.lat}`}>
                    {station.name} ({station.lat}, {station.lon})
                </p>
            ))}
            {mapMode && <MapCanvas features={features} onClick={place} />}
            <span
                data-testid="agency-marker"
                data-lat={agency.location.lat}
                data-lon={agency.location.lon}
                className="visually-hidden"
            >
                Marker
            </span>
            <label htmlFor="coverage">
                Coverage GeoJSON
                <textarea
                    id="coverage"
                    aria-label="Coverage GeoJSON"
                    value={coverageText}
                    onChange={(e) => setCoverageText(e.target.value)}
                />
            </label>
            <label htmlFor="coverage-file">
                Upload .geojson
                <input
                    id="coverage-file"
                    type="file"
                    accept=".geojson,application/geo+json"
                    onChange={upload}
                />
            </label>
            <fieldset>
                <legend>Linked tone sets</legend>
                {toneSets.map((tone) => (
                    <label className="inline-label" key={tone.id} htmlFor={`tone-${tone.id}`}>
                        <input
                            id={`tone-${tone.id}`}
                            type="checkbox"
                            checked={linked.has(tone.id)}
                            onChange={(event) =>
                                setLinked((old) => {
                                    const next = new Set(old);
                                    if (event.target.checked) next.add(tone.id);
                                    else next.delete(tone.id);
                                    return next;
                                })
                            }
                        />
                        {tone.name}
                    </label>
                ))}
            </fieldset>
            {error && (
                <p role="alert" className="error">
                    {error}
                </p>
            )}
            {id && incidents.length ? (
                <section aria-label="Recent CAD incidents">
                    <h2>Recent CAD incidents</h2>
                    {incidents.slice(0, 5).map((item) => (
                        <IncidentCard key={`${item.feed_id}-${item.incident_id}`} incident={item} />
                    ))}
                </section>
            ) : null}
            <button type="submit">Save agency</button>
        </form>
    );
}
