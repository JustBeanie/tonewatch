import { execFileSync, spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync } from "node:fs";
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
mkdirSync(dataDir, { recursive: true });
run(
    python,
    [
        join(repoRoot, "scripts", "e2e_fixture.py"),
        "--fixture",
        fixture,
        "--config",
        join(dataDir, "config.yaml"),
        "--source-path",
        fixture.replaceAll("\\", "/"),
    ],
    repoRoot,
);
console.error(`e2e fixture and config generated: ${fixture}`);

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
    setTimeout(() => process.exit(0), 1000).unref();
}

process.once("SIGTERM", stop);
process.once("SIGINT", stop);
process.once("disconnect", stop);
child.once("error", (error) => {
    console.error(error);
    process.exitCode = 1;
});
child.once("exit", (code) => {
    if (!stopping) process.exit(code ?? 1);
    else process.exit(0);
});
