import { useState } from "react";
import { apiUrl } from "../../lib/urls";
type Result = {
    segments?: { start_s: number; end_s: number; frequency: number }[];
    detections?: { toneset_id?: string; started_at?: string; confidence?: number }[];
};
export function Analyze() {
    const [result, setResult] = useState<Result>();
    const [error, setError] = useState("");
    const [progress, setProgress] = useState(0);
    async function upload(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (!file) return;
        if (file.size > 20 * 1024 * 1024) {
            setError("Upload too large: WAV files must be 20 MB or smaller.");
            return;
        }
        setError("");
        setProgress(20);
        const data = new FormData();
        data.append("file", file);
        const r = await fetch(apiUrl("analyze"), {
            method: "POST",
            body: data,
            credentials: "same-origin",
        });
        setProgress(100);
        if (!r.ok) {
            setError(
                r.status === 413
                    ? "The server rejected this upload because it is too large."
                    : r.status === 415
                      ? "The server expected a RIFF/WAVE audio file."
                      : "Analysis failed",
            );
            return;
        }
        setResult((await r.json()) as Result);
    }
    return (
        <>
            <h1>Analyze WAV</h1>
            <label htmlFor="wav">
                WAV file
                <input id="wav" type="file" accept="audio/wav,.wav" onChange={upload} />
            </label>
            {progress > 0 && <progress value={progress} max="100" aria-label="Upload progress" />}
            {error && (
                <p role="alert" className="error">
                    {error}
                </p>
            )}
            {result && (
                <>
                    <h2>Segments</h2>
                    <svg role="img" aria-label="Segment timeline" viewBox="0 0 800 120">
                        {(result.segments ?? []).map((s, i) => (
                            <g key={i}>
                                <rect
                                    x={s.start_s * 100}
                                    y="20"
                                    width={Math.max(2, (s.end_s - s.start_s) * 100)}
                                    height="40"
                                    fill="#2563eb"
                                />
                                <text x={s.start_s * 100} y="80">
                                    {s.frequency.toFixed(1)} Hz
                                </text>
                            </g>
                        ))}
                    </svg>
                    <h2>Detections</h2>
                    <table>
                        <thead>
                            <tr>
                                <th>Tone set</th>
                                <th>Time</th>
                                <th>Confidence</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(result.detections ?? []).map((d, i) => (
                                <tr key={i}>
                                    <td>{d.toneset_id}</td>
                                    <td>{d.started_at}</td>
                                    <td>{d.confidence}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </>
            )}
        </>
    );
}
