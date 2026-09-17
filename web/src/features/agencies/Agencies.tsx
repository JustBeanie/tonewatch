import { useEffect, useState } from "react";
import { Link } from "react-router";
import { request } from "../../api/client";
type Agency = {
    id: string;
    name: string;
    kind: string;
    location?: unknown;
    coverage?: unknown;
    stations?: unknown[];
    cad_names?: string[];
};
type Tone = { id: string; agency_id?: string | null };
export function Agencies() {
    const [items, setItems] = useState<Agency[]>([]);
    const [tones, setTones] = useState<Tone[]>([]);
    const reload = () =>
        request<Agency[]>("agencies")
            .then(setItems)
            .catch(() => undefined);
    useEffect(() => {
        void reload();
        request<Tone[]>("tonesets")
            .then((value) => {
                if (Array.isArray(value)) setTones(value);
            })
            .catch(() => undefined);
    }, []);
    async function remove(item: Agency) {
        if (!window.confirm(`Delete ${item.name}?`)) return;
        await request(`agencies/${item.id}`, { method: "DELETE" });
        void reload();
    }
    return (
        <>
            <h1>Agencies</h1>
            <Link to="/agencies/new">
                <button>New agency</button>
            </Link>
            <table>
                <caption className="visually-hidden">Configured agencies</caption>
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Kind</th>
                        <th>Tone sets</th>
                        <th>Location or coverage</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {items.map((item) => (
                        <tr key={item.id}>
                            <th scope="row">
                                <Link to={`/agencies/${item.id}/edit`}>{item.name}</Link>
                            </th>
                            <td>{item.kind}</td>
                            <td>{tones.filter((tone) => tone.agency_id === item.id).length}</td>
                            <td>{item.location || item.coverage ? "Yes" : "No"}</td>
                            <td>
                                <button className="danger" onClick={() => void remove(item)}>
                                    Delete
                                </button>
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </>
    );
}
