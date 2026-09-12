import { execFileSync, spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDir, "..");
const repoRoot = resolve(webRoot, "..");
const port = process.env.TONEWATCH_E2E_PORT || "8765";
const testRoot = join(webRoot, "test-results");
const runId = `${process.pid}-${Date.now()}`;
const dataDir = join(testRoot, `e2e-data-${runId}`);
const fixture = join(testRoot, `fixture-${runId}.wav`);
const localPython = join(
    repoRoot,
    "backend",
    ".venv",
    process.platform === "win32" ? "Scripts\\python.exe" : "bin/python",
);
const python = existsSync(localPython) ? localPython : "python";
console.error(`e2e launcher starting on port ${port}`);

function run(command, args, cwd) {
    if (process.platform === "win32" && command.toLowerCase().endsWith(".cmd")) {
        const quote = (value) => {
            const text = String(value);
            return /[\s"]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
        };
        const commandLine = [command, ...args].map(quote).join(" ");
        execFileSync(process.env.ComSpec || "cmd.exe", ["/d", "/c", commandLine], {
            cwd,
            stdio: "ignore",
            windowsHide: true,
        });
        return;
    }
    execFileSync(command, args, { cwd, stdio: "ignore", windowsHide: true });
}

mkdirSync(testRoot, { recursive: true });
run(process.execPath, [join(webRoot, "node_modules", "vite", "bin", "vite.js"), "build"], webRoot);

const generator = [
    "from pathlib import Path",
    "import wave",
    "import numpy as np",
    "from tonewatch.dsp.generator import concat, silence, tone, voice_like",
    `path = Path(${JSON.stringify(fixture.replaceAll("\\", "/"))})`,
    "samples = concat(silence(0.5), tone(1000, 1.0, 0.5), silence(0.15), tone(1500, 3.0, 0.5), voice_like(4.0, seed=17))",
    'with wave.open(str(path), "wb") as output:',
    "    output.setnchannels(1)",
    "    output.setsampwidth(2)",
    "    output.setframerate(16000)",
    '    output.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())',
].join("\n");
run(python, ["-c", generator], repoRoot);
console.error(`e2e fixture generated: ${fixture}`);

const yamlPath = fixture.replaceAll("\\", "/");
const config = [
    "tone_sets:",
    "  - id: fixture-page",
    "    name: Fixture page",
    "    sequence:",
    "      - freq_hz: 1000",
    "        tol_pct: 2",
    "        min_s: 0.8",
    "        max_s: 1.3",
    "      - freq_hz: 1500",
    "        tol_pct: 2",
    "        min_s: 2.5",
    "        max_s: 3.5",
    "    cooldown_s: 0",
    "    record:",
    "      pre_roll_s: 0.2",
    "      post_s: 2",
    "      silence_stop_s: 8",
    "      max_s: 15",
    "      formats: [mp3]",
    "sources:",
    "  - id: fixture-radio",
    "    name: Fixture radio",
    "    type: file",
    `    path: "${yamlPath}"`,
    "    realtime: true",
    "    loop: true",
    "    tonesets: [fixture-page]",
    "alert_targets: []",
].join("\n");
mkdirSync(dataDir, { recursive: true });
writeFileSync(join(dataDir, "config.yaml"), config, "utf8");
console.error(`e2e config written: ${join(dataDir, "config.yaml")}`);

const env = {
    ...process.env,
    TONEWATCH_BIND_HOST: "127.0.0.1",
    TONEWATCH_BIND_PORT: port,
    TONEWATCH_DATA_DIR: dataDir,
    TONEWATCH_RECORDINGS_ROOT: join(dataDir, "recordings"),
    TONEWATCH_UI_PASSWORD: "e2e-password",
    TONEWATCH_WEB_ROOT: join(webRoot, "dist"),
    TONEWATCH_ZEROCONF_ENABLED: "false",
};
const child = spawn(python, ["-m", "tonewatch", "serve"], {
    cwd: repoRoot,
    env,
    stdio: "ignore",
    windowsHide: true,
});
let stopping = false;

function stop() {
    if (stopping) return;
    stopping = true;
    if (child.pid && process.platform === "win32") {
        spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
            stdio: "inherit",
            windowsHide: true,
        });
    } else {
        child.kill("SIGTERM");
    }
}

process.once("SIGTERM", stop);
process.once("SIGINT", stop);
process.once("disconnect", stop);
process.stdin.resume();
process.stdin.once("end", stop);
process.stdin.once("close", stop);
child.once("error", (error) => {
    console.error(error);
    process.exitCode = 1;
});
child.once("exit", (code) => {
    if (!stopping) process.exit(code ?? 1);
    else process.exit(0);
});
