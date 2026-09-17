import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { request } from "../../api/client";
type Call = { id: string; started_at: string; source_id: string; status: string };
type Agency = { id: string; name: string };
type Detail = Call & {
    tone_sets: {
        toneset_id: string;
        detected_at: string;
        agency?: { id: string; name: string; kind: string } | null;
    }[];
    recordings: { id: number; format: string; url: string }[];
    alert_attempts: Record<string, unknown>[];
};
export function Calls() {
    const [p, setP] = useSearchParams();
    const [items, setItems] = useState<Call[]>([]);
    const [agencies, setAgencies] = useState<Agency[]>([]);
    useEffect(() => {
        request<Agency[]>("agencies")
            .then((value) => {
                if (Array.isArray(value)) setAgencies(value);
            })
            .catch(() => undefined);
    }, []);
    useEffect(() => {
        const q = new URLSearchParams(p);
        q.set("limit", "50");
        request<{ items: Call[] }>(`calls?${q}`)
            .then((v) => setItems(v.items))
            .catch(() => undefined);
    }, [p]);
    return (
        <>
            <h1>Calls</h1>
            <form
                className="card"
                onSubmit={(e) => {
                    e.preventDefault();
                    const f = new FormData(e.currentTarget);
                    setP((o) => {
                        const n = new URLSearchParams(o);
                        ["source", "toneset", "agency_id", "since", "until"].forEach((k) => {
                            const v = String(f.get(k) || "");
                            v ? n.set(k, v) : n.delete(k);
                        });
                        return n;
                    });
                }}
            >
                <label htmlFor="source">
                    Source
                    <input id="source" name="source" defaultValue={p.get("source") ?? ""} />
                </label>
                <label htmlFor="agency_id">
                    Agency
                    <select id="agency_id" name="agency_id" defaultValue={p.get("agency_id") ?? ""}>
                        <option value="">All agencies</option>
                        {agencies.map((agency) => (
                            <option key={agency.id} value={agency.id}>
                                {agency.name}
                            </option>
                        ))}
                    </select>
                </label>
                <label htmlFor="toneset">
                    Tone set
                    <input id="toneset" name="toneset" defaultValue={p.get("toneset") ?? ""} />
                </label>
                <label htmlFor="since">
                    From
                    <input id="since" name="since" type="date" />
                </label>
                <label htmlFor="until">
                    To
                    <input id="until" name="until" type="date" />
                </label>
                <button>Filter</button>
            </form>
            {items.length ? (
                items.map((c) => (
                    <p key={c.id}>
                        <Link to={`/calls/${c.id}`}>
                            {c.started_at} · {c.source_id} · {c.status}
                        </Link>
                    </p>
                ))
            ) : (
                <p>No calls found.</p>
            )}
        </>
    );
}
export function CallDetail() {
    const { id } = useParams();
    const [d, setD] = useState<Detail>();
    const [fmt, setFmt] = useState("");
    useEffect(() => {
        if (id)
            request<Detail>(`calls/${id}`)
                .then(setD)
                .catch(() => undefined);
    }, [id]);
    if (!d) return <p>Loading call…</p>;
    const r = d.recordings.find((x) => x.format === fmt) || d.recordings[0];
    return (
        <>
            <h1>Call {d.id}</h1>
            <p>
                {d.started_at} · {d.source_id}
            </p>
            <h2>Matched tone sets</h2>
            <ul>
                {d.tone_sets.map((t) => (
                    <li key={t.toneset_id}>
                        {t.toneset_id} at {t.detected_at}
                        {t.agency ? ` · ${t.agency.name} (${t.agency.kind})` : ""}
                    </li>
                ))}
            </ul>
            {d.recordings.length > 1 && (
                <label htmlFor="format">
                    Format
                    <select
                        id="format"
                        value={fmt || d.recordings[0]?.format || ""}
                        onChange={(e) => setFmt(e.target.value)}
                    >
                        {d.recordings.map((x) => (
                            <option key={x.format}>{x.format}</option>
                        ))}
                    </select>
                </label>
            )}
            {r && (
                <>
                    <audio controls src={r.url} />
                    <a href={r.url} download>
                        Download recording
                    </a>
                </>
            )}
            <h2>Alert attempts</h2>
            {d.alert_attempts.length ? (
                <table>
                    <tbody>
                        {d.alert_attempts.map((a, i) => (
                            <tr key={i}>
                                <td>{String(a.status ?? "attempt")}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            ) : (
                <p>No alert attempts.</p>
            )}
        </>
    );
}
