import { useEffect, useState } from "react";
import { request } from "../../api/client";
type Target = { id: string; name?: string; type: string; enabled?: boolean; secret_set?: boolean };
export function Alerts() {
    const [items, setItems] = useState<Target[]>([]);
    const [error, setError] = useState("");
    useEffect(() => {
        request<Target[]>("alert-targets")
            .then(setItems)
            .catch(() => undefined);
    }, []);
    async function save(e: React.FormEvent<HTMLFormElement>) {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        try {
            await request("alert-targets", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    id: crypto.randomUUID(),
                    name: f.get("name"),
                    type: f.get("type"),
                    secret: f.get("secret") || undefined,
                    enabled: true,
                }),
            });
            setItems(await request<Target[]>("alert-targets"));
        } catch (e) {
            setError(
                (e as { status?: number }).status === 403
                    ? "Script targets are disabled on this server"
                    : "Unable to save target",
            );
        }
    }
    return (
        <>
            <h1>Alerts</h1>
            {items.map((i) => (
                <div className="card" key={i.id}>
                    <b>{i.name ?? i.id}</b> · {i.type}
                    {i.type === "webhook" && (
                        <span>
                            {" "}
                            — {i.secret_set ? "secret set" : "no secret"}; secrets are write-only.{" "}
                            <button type="button">Replace secret</button>
                        </span>
                    )}
                    {i.type === "script" && (
                        <p role="alert">
                            <strong>Warning: scripts execute on the server.</strong>
                        </p>
                    )}
                    <button
                        type="button"
                        onClick={() => request("tonesets/t1/test", { method: "POST" })}
                    >
                        Send test
                    </button>
                </div>
            ))}
            <form className="form" onSubmit={save}>
                <label htmlFor="alert-name">
                    Name
                    <input id="alert-name" name="name" required />
                </label>
                <label htmlFor="alert-type">
                    Type
                    <select id="alert-type" name="type">
                        <option>mqtt</option>
                        <option>webhook</option>
                        <option>script</option>
                    </select>
                </label>
                <label htmlFor="secret">
                    Webhook secret (write-only)
                    <input id="secret" name="secret" type="password" autoComplete="new-password" />
                </label>
                <button>Save target</button>
                {error && (
                    <p role="alert" className="error">
                        {error}
                    </p>
                )}
            </form>
        </>
    );
}
