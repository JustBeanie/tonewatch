import { FormEvent, lazy, useEffect, useState } from "react";
import { Link, Route, Routes, useNavigate } from "react-router";
import { Boundary } from "./Boundary";
import { Shell } from "./Shell";
import { request } from "../api/client";
import { Dashboard } from "../features/dashboard/Dashboard";
import { Calls, CallDetail } from "../features/calls/Calls";
import { ToneSets, ToneSetForm } from "../features/tonesets/ToneSets";
import { DiscoveredTones } from "../features/discovered/DiscoveredTones";
import { Spectrum } from "../features/spectrum/Spectrum";
import { Sources } from "../features/sources/Sources";
import { Alerts } from "../features/alerts/Alerts";
import { Settings } from "../features/settings/Settings";
import { Analyze } from "../features/analyze/Analyze";
import { Agencies } from "../features/agencies/Agencies";
import { AgencyForm } from "../features/agencies/AgencyForm";
import { CadFeeds, UnmatchedCadAgencies } from "../features/cad/CadFeeds";

const MapPage = lazy(() =>
    import("../features/map/MapPage").then(({ MapPage }) => ({ default: MapPage })),
);
const Health = lazy(() =>
    import("../features/admin/Health").then(({ Health }) => ({ default: Health })),
);
const AdminAlerts = lazy(() =>
    import("../features/admin/AdminAlerts").then(({ AdminAlerts }) => ({ default: AdminAlerts })),
);
const Deliveries = lazy(() =>
    import("../features/admin/Deliveries").then(({ Deliveries }) => ({ default: Deliveries })),
);
const Credentials = lazy(() =>
    import("../features/admin/Credentials").then(({ Credentials }) => ({ default: Credentials })),
);
const Maintenance = lazy(() =>
    import("../features/admin/Maintenance").then(({ Maintenance }) => ({ default: Maintenance })),
);
const Audit = lazy(() =>
    import("../features/admin/Audit").then(({ Audit }) => ({ default: Audit })),
);
const Drill = lazy(() =>
    import("../features/admin/Drill").then(({ Drill }) => ({ default: Drill })),
);
const ConfigHistory = lazy(() =>
    import("../features/admin/ConfigHistory").then(({ ConfigHistory }) => ({
        default: ConfigHistory,
    })),
);
const Logs = lazy(() => import("../features/admin/Logs").then(({ Logs }) => ({ default: Logs })));
const Backup = lazy(() =>
    import("../features/admin/Backup").then(({ Backup }) => ({ default: Backup })),
);
const Replay = lazy(() =>
    import("../features/admin/Replay").then(({ Replay }) => ({ default: Replay })),
);

function Login() {
    const [password, setPassword] = useState("");
    const [error, setError] = useState("");
    const nav = useNavigate();
    useEffect(() => {
        request<{ authenticated: boolean; password_required: boolean }>("auth/status")
            .then((s) => {
                if (s.authenticated || !s.password_required) nav("/");
            })
            .catch(() => undefined);
    }, [nav]);
    async function submit(e: FormEvent) {
        e.preventDefault();
        try {
            await request("auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ password }),
            });
            nav("/");
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
export function Router() {
    return (
        <Boundary>
            <Routes>
                <Route path="/login" element={<Login />} />
                <Route element={<Shell />}>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/calls" element={<Calls />} />
                    <Route path="/calls/:id" element={<CallDetail />} />
                    <Route path="/agencies" element={<Agencies />} />
                    <Route path="/agencies/new" element={<AgencyForm />} />
                    <Route path="/agencies/:id/edit" element={<AgencyForm />} />
                    <Route path="/map" element={<MapPage />} />
                    <Route path="/tonesets" element={<ToneSets />} />
                    <Route path="/discovered-tones" element={<DiscoveredTones />} />
                    <Route path="/tonesets/new" element={<ToneSetForm />} />
                    <Route path="/tonesets/:id/edit" element={<ToneSetForm />} />
                    <Route path="/spectrum" element={<Spectrum />} />
                    <Route path="/sources" element={<Sources />} />
                    <Route path="/alerts" element={<Alerts />} />
                    <Route path="/settings" element={<Settings />} />
                    <Route path="/settings/cad-feeds" element={<CadFeeds />} />
                    <Route path="/cad/unmatched-agencies" element={<UnmatchedCadAgencies />} />
                    <Route path="/analyze" element={<Analyze />} />
                    <Route path="/admin/health" element={<Health />} />
                    <Route path="/admin/alerts" element={<AdminAlerts />} />
                    <Route path="/admin/deliveries" element={<Deliveries />} />
                    <Route path="/admin/credentials" element={<Credentials />} />
                    <Route path="/admin/maintenance" element={<Maintenance />} />
                    <Route path="/admin/audit" element={<Audit />} />
                    <Route path="/admin/drill" element={<Drill />} />
                    <Route path="/admin/config" element={<ConfigHistory />} />
                    <Route path="/admin/logs" element={<Logs />} />
                    <Route path="/admin/backup" element={<Backup />} />
                    <Route path="/admin/replay" element={<Replay />} />
                    <Route
                        path="*"
                        element={
                            <>
                                <h1>Not found</h1>
                                <Link to="/">Dashboard</Link>
                            </>
                        }
                    />
                </Route>
            </Routes>
        </Boundary>
    );
}
