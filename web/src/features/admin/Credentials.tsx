import { useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { request } from "../../api/client";
import { errorText, formatExpiry } from "./shared";

type Failure = { status?: number; body?: { detail?: unknown } };

export function Credentials() {
    const nav = useNavigate();
    const [ingress, setIngress] = useState(false);
    const [grace, setGrace] = useState("3600");
    const [token, setToken] = useState<{ value: string; until: number | null } | null>(null);
    const [message, setMessage] = useState("");
    const [error, setError] = useState("");
    const [current, setCurrent] = useState("");
    const [next, setNext] = useState("");
    const [confirm, setConfirm] = useState("");
    useEffect(() => {
        void request<{ via?: string }>("auth/status").then((status) =>
            setIngress(status.via === "ingress"),
        );
    }, []);
    function clearPasswords() {
        setCurrent("");
        setNext("");
        setConfirm("");
    }
    async function rotateToken() {
        if (!window.confirm("Rotate the API token? The new token will be shown only once.")) return;
        try {
            const result = await request<{ token: string; previous_valid_until: number | null }>(
                "admin/credentials/api-token/rotate",
                { method: "POST", body: JSON.stringify({ grace_seconds: Number(grace) }) },
            );
            setToken({ value: result.token, until: result.previous_valid_until });
            setMessage("New token generated.");
        } catch (reason: unknown) {
            setError(errorText(reason));
        }
    }
    async function rotateLive() {
        if (
            !window.confirm("Rotate the live secret? All live links stop and listeners disconnect.")
        )
            return;
        try {
            await request("admin/credentials/live-secret/rotate", { method: "POST" });
            setMessage("Live secret rotated; listeners disconnected.");
        } catch (reason: unknown) {
            setError(errorText(reason));
        }
    }
    async function changePassword() {
        setError("");
        if (next.length < 12) {
            setError("New password must be at least 12 characters");
            clearPasswords();
            return;
        }
        if (next !== confirm) {
            setError("New password and confirmation do not match");
            clearPasswords();
            return;
        }
        try {
            await request("admin/credentials/ui-password", {
                method: "POST",
                body: JSON.stringify({ current_password: current, new_password: next }),
            });
            setMessage("UI password changed.");
        } catch (reason: unknown) {
            const failure = reason as Failure;
            setError(
                failure.status === 403
                    ? "Current password is incorrect"
                    : failure.status === 429
                      ? "Too many attempts, wait"
                      : errorText(reason),
            );
        } finally {
            clearPasswords();
        }
    }
    async function revoke() {
        if (!window.confirm("Revoke all sessions? This signs everyone out, including you.")) return;
        await request("admin/credentials/sessions/revoke-all", { method: "POST" });
        nav("/login");
    }
    if (ingress)
        return (
            <>
                <h1>Credentials</h1>
                <p role="status">
                    Credential changes require direct access, not the trusted ingress.
                </p>
            </>
        );
    return (
        <>
            <h1>Credentials</h1>
            {message && <p role="status">{message}</p>}
            {error && <p role="alert">{error}</p>}
            <section className="card">
                <h2>API token</h2>
                <label htmlFor="token-grace">Old token grace period</label>
                <select id="token-grace" value={grace} onChange={(e) => setGrace(e.target.value)}>
                    <option value="0">Immediately</option>
                    <option value="300">5 minutes</option>
                    <option value="3600">1 hour</option>
                    <option value="86400">24 hours</option>
                </select>
                <button onClick={() => void rotateToken()}>Rotate API token</button>
                {token && (
                    <div role="alert">
                        <p>This is the only time the new token is shown. Copy it now.</p>
                        <input aria-label="New API token" readOnly value={token.value} />
                        {token.until && <p>Old token valid until {formatExpiry(token.until)}.</p>}
                        <p>
                            If this page uses the bearer token, it stops working when the old token
                            expires.
                        </p>
                    </div>
                )}
            </section>
            <section className="card">
                <h2>Live secret</h2>
                <p>Rotating stops all live links and disconnects listeners.</p>
                <button onClick={() => void rotateLive()}>Rotate live secret</button>
            </section>
            <section className="card">
                <h2>UI password</h2>
                <label htmlFor="current-password">
                    Current password
                    <input
                        id="current-password"
                        type="password"
                        autoComplete="current-password"
                        value={current}
                        onChange={(e) => setCurrent(e.target.value)}
                    />
                </label>
                <label htmlFor="new-password">
                    New password
                    <input
                        id="new-password"
                        type="password"
                        autoComplete="new-password"
                        value={next}
                        onChange={(e) => setNext(e.target.value)}
                    />
                </label>
                <label htmlFor="confirm-password">
                    Confirm new password
                    <input
                        id="confirm-password"
                        type="password"
                        autoComplete="new-password"
                        value={confirm}
                        onChange={(e) => setConfirm(e.target.value)}
                    />
                </label>
                <button onClick={() => void changePassword()}>Change UI password</button>
            </section>
            <section className="card">
                <h2>Sessions</h2>
                <p>Revoke every session, including your own.</p>
                <button onClick={() => void revoke()}>Revoke all sessions</button>
            </section>
        </>
    );
}
