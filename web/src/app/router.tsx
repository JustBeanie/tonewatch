import { FormEvent, useEffect, useState } from "react";
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
import { MapPage } from "../features/map/MapPage";
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
                    <Route path="/analyze" element={<Analyze />} />
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
