import { FormEvent, ReactNode, useEffect, useState } from "react";
import {
    BrowserRouter,
    Link,
    NavLink,
    Route,
    Routes,
    useNavigate,
    useParams,
    useSearchParams,
} from "react-router";
import { request } from "./api/client";
import { useSubscription } from "./lib/ws";
import "./styles.css";

type Tone = { frequency: number; tolerance_pct: number; min_s: number; max_s: number };
type ToneSet = {
    id: string;
    name: string;
    enabled: boolean;
    sequence: Tone[];
    record?: Record<string, unknown>;
    alert_targets?: string[];
};
type Call = { id: string; started_at: string; source_id: string; status: string };
type Detail = Call & {
    tone_sets: { toneset_id: string; detected_at: string }[];
    recordings: { id: number; format: string; url: string }[];
    alert_attempts: Record<string, unknown>[];
};

function Boundary({ children }: { children: ReactNode }) {
    return <>{children}</>;
}
function Shell() {
    const [dark, setDark] = useState(() => {
        try {
            return localStorage.getItem("tonewatch-theme") === "dark";
        } catch {
            return false;
        }
    });
    const navigate = useNavigate();
    useEffect(() => {
        document.documentElement.dataset.theme = dark ? "dark" : "light";
        try {
            localStorage.setItem("tonewatch-theme", dark ? "dark" : "light");
        } catch {
            /* storage is optional */
        }
    }, [dark]);
    async function logout() {
        await request("auth/logout", { method: "POST" });
        navigate("/login");
    }
    return (
        <div className="app">
            <aside className="sidebar">
                <h1>ToneWatch</h1>
                <nav aria-label="Main navigation">
                    <NavLink to="/">Dashboard</NavLink>
                    <NavLink to="/calls">Calls</NavLink>
                    <NavLink to="/tonesets">Tone sets</NavLink>
                </nav>
                <button className="secondary" onClick={() => setDark(!dark)}>
                    {dark ? "Light theme" : "Dark theme"}
                </button>
                <button className="secondary" onClick={logout}>
                    Log out
                </button>
            </aside>
            <main className="content">
                <Boundary>
                    <Routes>
                        <Route path="/" element={<Dashboard />} />
                        <Route path="/calls" element={<Calls />} />
                        <Route path="/calls/:id" element={<CallDetail />} />
                        <Route path="/tonesets" element={<ToneSets />} />
                        <Route path="/tonesets/new" element={<ToneSetForm />} />
                        <Route path="/tonesets/:id/edit" element={<ToneSetForm />} />
                        <Route
                            path="*"
                            element={
                                <>
                                    <h1>Not found</h1>
                                    <Link to="/">Dashboard</Link>
                                </>
                            }
                        />
                    </Routes>
                </Boundary>
            </main>
        </div>
    );
}
function Login() {
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const navigate = useNavigate();
    useEffect(() => {
        request<{ authenticated: boolean; password_required: boolean }>("auth/status")
            .then((s) => {
                if (s.authenticated || !s.password_required) navigate("/");
            })
            .catch(() => undefined);
    }, [navigate]);
    async function submit(event: FormEvent) {
        event.preventDefault();
        setError("");
        try {
            await request("auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password }),
            });
            navigate("/");
        } catch {
            setError("Login failed");
        }
    }
    return (
        <main className="content">
            <h1>Sign in to ToneWatch</h1>
            <form className="form" onSubmit={submit}>
                <label htmlFor="password">
                    Password
                    <input
                        id="password"
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        required
                    />
                </label>
                <button>Sign in</button>
                {error && <p className="error">{error}</p>}
            </form>
        </main>
    );
}
function Dashboard() {
    const event = useSubscription("events");
    const level = useSubscription("levels");
    const [calls, setCalls] = useState<Call[]>([]);
    useEffect(() => {
        request<{ items?: Call[] }>("calls?limit=50")
            .then((v) => setCalls(v.items ?? []))
            .catch(() => undefined);
    }, []);
    useEffect(() => {
        const data = event?.data;
        if (!data) return;
        if (["ToneDetected", "RecordingReady", "CallClosed"].includes(event.type))
            setCalls((old) =>
                [
                    {
                        ...(data as unknown as Call),
                        id: String(data.id ?? data.call_id ?? crypto.randomUUID()),
                    },
                    ...old,
                ].slice(0, 50),
            );
    }, [event]);
    const db = Number(level?.data?.dbfs ?? -100);
    const health = event?.type === "FeedHealthChanged" ? String(event.data?.reason ?? "") : "";
    return (
        <>
            <h1>Dashboard</h1>
            {health && <p role="status">Feed health: {health}</p>}
            <section className="grid">
                <div className="card">
                    <h2>Channel levels</h2>
                    <div
                        role="meter"
                        aria-label="Audio level"
                        aria-valuemin={-100}
                        aria-valuemax={0}
                        aria-valuenow={db}
                    >
                        {db.toFixed(1)} dBFS
                    </div>
                </div>
                <div className="card">
                    <h2>Live calls</h2>
                    {calls.length ? (
                        calls.map((call) => (
                            <Link key={call.id} to={`/calls/${call.id}`}>
                                <p>
                                    {call.source_id} · {call.status} · {call.started_at}
                                </p>
                            </Link>
                        ))
                    ) : (
                        <p>
                            No calls yet. <Link to="/sources">Configure a source</Link>.
                        </p>
                    )}
                </div>
            </section>
        </>
    );
}
function Calls() {
    const [params, setParams] = useSearchParams();
    const [items, setItems] = useState<Call[]>([]);
    const source = params.get("source") ?? "";
    const tone = params.get("toneset") ?? "";
    useEffect(() => {
        const query = new URLSearchParams(params);
        query.set("limit", "50");
        request<{ items: Call[] }>(`calls?${query}`)
            .then((v) => setItems(v.items))
            .catch(() => undefined);
    }, [params]);
    return (
        <>
            <h1>Calls</h1>
            <form
                className="card"
                onSubmit={(e) => {
                    e.preventDefault();
                    const form = new FormData(e.currentTarget);
                    setParams((old) => {
                        const next = new URLSearchParams(old);
                        ["source", "toneset", "since", "until"].forEach((key) => {
                            const value = String(form.get(key) ?? "");
                            if (value) next.set(key, value);
                            else next.delete(key);
                        });
                        return next;
                    });
                }}
            >
                <label htmlFor="source">
                    Source
                    <input id="source" name="source" defaultValue={source} />
                </label>
                <label htmlFor="toneset">
                    Tone set
                    <input id="toneset" name="toneset" defaultValue={tone} />
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
            <section>
                {items.length ? (
                    items.map((call) => (
                        <p key={call.id}>
                            <Link to={`/calls/${call.id}`}>
                                {call.started_at} · {call.source_id} · {call.status}
                            </Link>
                        </p>
                    ))
                ) : (
                    <p>No calls found.</p>
                )}
            </section>
        </>
    );
}
function CallDetail() {
    const { id } = useParams();
    const [detail, setDetail] = useState<Detail>();
    const [format, setFormat] = useState("");
    useEffect(() => {
        if (id)
            request<Detail>(`calls/${id}`)
                .then(setDetail)
                .catch(() => undefined);
    }, [id]);
    const recordings = detail?.recordings ?? [];
    const selected = recordings.find((r) => r.format === format) ?? recordings[0];
    if (!detail) return <p>Loading call…</p>;
    return (
        <>
            <h1>Call {detail.id}</h1>
            <p>
                {detail.started_at} · {detail.source_id}
            </p>
            <h2>Matched tone sets</h2>
            <ul>
                {detail.tone_sets.map((tone) => (
                    <li key={tone.toneset_id}>
                        {tone.toneset_id} at {tone.detected_at}
                    </li>
                ))}
            </ul>
            {recordings.length > 1 && (
                <label htmlFor="format">
                    Format
                    <select
                        id="format"
                        value={format || recordings[0]?.format || ""}
                        onChange={(e) => setFormat(e.target.value)}
                    >
                        {recordings.map((r) => (
                            <option key={r.format}>{r.format}</option>
                        ))}
                    </select>
                </label>
            )}
            {selected && (
                <>
                    <audio controls src={selected.url} />
                    <a href={selected.url} download>
                        Download recording
                    </a>
                </>
            )}
            <h2>Alert attempts</h2>
            {detail.alert_attempts.length ? (
                <table>
                    <tbody>
                        {detail.alert_attempts.map((a, i) => (
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
function ToneSets() {
    const [items, setItems] = useState<ToneSet[]>([]);
    const reload = () =>
        request<ToneSet[]>("tonesets")
            .then(setItems)
            .catch(() => undefined);
    useEffect(() => {
        void reload();
    }, []);
    async function toggle(item: ToneSet) {
        await request(`tonesets/${item.id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ...item, enabled: !item.enabled }),
        });
        void reload();
    }
    async function remove(item: ToneSet) {
        if (!window.confirm(`Delete ${item.name}?`)) return;
        try {
            await request(`tonesets/${item.id}`, { method: "DELETE" });
            void reload();
        } catch (error) {
            if ((error as { status?: number }).status === 409) {
                const refs =
                    (error as { body?: { detail?: { referrers?: string[] } } }).body?.detail
                        ?.referrers ?? [];
                window.alert(`Referenced by: ${refs.join(", ")}`);
            }
        }
    }
    return (
        <>
            <h1>Tone sets</h1>
            <Link to="/tonesets/new">
                <button>New tone set</button>
            </Link>
            {items.map((item) => (
                <div className="card" key={item.id}>
                    <b>{item.name}</b>
                    <label htmlFor={`enabled-${item.id}`}>
                        Enabled
                        <input
                            id={`enabled-${item.id}`}
                            type="checkbox"
                            checked={item.enabled}
                            onChange={() => toggle(item)}
                        />
                    </label>
                    <Link to={`/tonesets/${item.id}/edit`}>Edit</Link>
                    <button className="danger" onClick={() => remove(item)}>
                        Delete
                    </button>
                    <button onClick={() => request(`tonesets/${item.id}/test`, { method: "POST" })}>
                        Test
                    </button>
                </div>
            ))}
        </>
    );
}
function ToneSetForm() {
    const { id } = useParams();
    const navigate = useNavigate();
    const [name, setName] = useState("");
    const [tones, setTones] = useState<Tone[]>([
        { frequency: 1000, tolerance_pct: 1, min_s: 0.5, max_s: 3 },
    ]);
    const [error, setError] = useState("");
    useEffect(() => {
        if (id)
            request<ToneSet>(`tonesets/${id}`)
                .then((item) => {
                    setName(item.name);
                    setTones(item.sequence);
                })
                .catch(() => undefined);
    }, [id]);
    function validate() {
        return tones.some(
            (tone) =>
                tone.frequency < 250 ||
                tone.frequency > 3000 ||
                tone.tolerance_pct < 0.1 ||
                tone.tolerance_pct > 10 ||
                tone.max_s < tone.min_s,
        )
            ? "Check frequency, tolerance, and duration ranges."
            : "";
    }
    async function save(event: FormEvent) {
        event.preventDefault();
        const invalid = validate();
        if (invalid) {
            setError(invalid);
            return;
        }
        try {
            await request(`tonesets${id ? `/${id}` : ""}`, {
                method: id ? "PUT" : "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    id: id ?? crypto.randomUUID(),
                    name,
                    enabled: true,
                    sequence: tones,
                }),
            });
            navigate("/tonesets");
        } catch (e) {
            const body = (
                e as { body?: { detail?: { loc?: (string | number)[]; msg?: string }[] } }
            ).body;
            setError(
                body?.detail?.map((d) => `${d.loc?.join(".")}: ${d.msg}`).join("; ") ??
                    "Unable to save tone set",
            );
        }
    }
    return (
        <>
            <h1>{id ? "Edit" : "Create"} tone set</h1>
            <form className="form" onSubmit={save}>
                <label htmlFor="name">
                    Name
                    <input
                        id="name"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        required
                    />
                </label>
                {tones.map((tone, index) => (
                    <fieldset key={index}>
                        <legend>Tone {index + 1}</legend>
                        {(["frequency", "tolerance_pct", "min_s", "max_s"] as const).map(
                            (field) => (
                                <label key={field} htmlFor={`${field}-${index}`}>
                                    {field}
                                    <input
                                        id={`${field}-${index}`}
                                        type="number"
                                        step="any"
                                        value={tone[field]}
                                        onChange={(e) =>
                                            setTones((old) =>
                                                old.map((item, i) =>
                                                    i === index
                                                        ? {
                                                              ...item,
                                                              [field]: Number(e.target.value),
                                                          }
                                                        : item,
                                                ),
                                            )
                                        }
                                    />
                                </label>
                            ),
                        )}
                    </fieldset>
                ))}
                {tones.length < 8 && (
                    <button
                        type="button"
                        className="secondary"
                        onClick={() =>
                            setTones([
                                ...tones,
                                { frequency: 1000, tolerance_pct: 1, min_s: 0.5, max_s: 3 },
                            ])
                        }
                    >
                        Add tone
                    </button>
                )}
                <label htmlFor="record-policy">
                    Recording policy
                    <input id="record-policy" placeholder="Default policy" />
                </label>
                <label htmlFor="alert-targets">
                    Alert targets
                    <select id="alert-targets" multiple>
                        <option>Choose targets in the next step</option>
                    </select>
                </label>
                <button>Save</button>
                <button
                    type="button"
                    className="secondary"
                    title="TTD import requires a sample configuration"
                >
                    Import TTD (unavailable)
                </button>
                {error && (
                    <p className="error" role="alert">
                        {error}
                    </p>
                )}
            </form>
        </>
    );
}
export function App() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route path="*" element={<Shell />} />
            </Routes>
        </BrowserRouter>
    );
}
