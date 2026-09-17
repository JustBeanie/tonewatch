import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router";
import { request } from "../api/client";
export function Shell() {
    const [dark, setDark] = useState(() => localStorage.getItem("tonewatch-theme") === "dark");
    const nav = useNavigate();
    useEffect(() => {
        document.documentElement.dataset.theme = dark ? "dark" : "light";
        localStorage.setItem("tonewatch-theme", dark ? "dark" : "light");
    }, [dark]);
    return (
        <div className="app">
            <aside className="sidebar">
                <h1>ToneWatch</h1>
                <nav aria-label="Main navigation">
                    {(
                        [
                            ["/", "Dashboard"],
                            ["/calls", "Calls"],
                            ["/map", "Map"],
                            ["/agencies", "Agencies"],
                            ["/tonesets", "Tone sets"],
                            ["/discovered-tones", "Discovered tones"],
                            ["/spectrum", "Spectrum"],
                            ["/sources", "Sources"],
                            ["/alerts", "Alerts"],
                            ["/settings", "Settings"],
                            ["/settings/cad-feeds", "CAD feeds"],
                            ["/cad/unmatched-agencies", "Unmatched CAD agencies"],
                            ["/analyze", "Analyze"],
                        ] as [string, string][]
                    ).map(([to, label]) => (
                        <NavLink key={to} to={to}>
                            {label}
                        </NavLink>
                    ))}
                </nav>
                <button className="secondary" onClick={() => setDark(!dark)}>
                    {dark ? "Light theme" : "Dark theme"}
                </button>
                <button
                    className="secondary"
                    onClick={async () => {
                        await request("auth/logout", { method: "POST" });
                        nav("/login");
                    }}
                >
                    Log out
                </button>
            </aside>
            <main className="content">
                <Outlet />
            </main>
        </div>
    );
}
