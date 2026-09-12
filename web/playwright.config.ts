import { defineConfig } from "playwright/test";

const port = process.env.TONEWATCH_E2E_PORT || "8765";

export default defineConfig({
    testDir: "./e2e",
    timeout: 30000,
    fullyParallel: false,
    reporter: [["list"], ["html", { outputFolder: "./playwright-report", open: "never" }]],
    outputDir: "./test-results",
    use: {
        baseURL: `http://127.0.0.1:${port}`,
        channel: process.env.PLAYWRIGHT_CHANNEL || undefined,
        trace: "off",
        screenshot: "only-on-failure",
        video: "off",
    },
    webServer: {
        command: "node e2e/start.mjs",
        url: `http://127.0.0.1:${port}/readyz`,
        reuseExistingServer: false,
        timeout: 180000,
        stdout: "pipe",
        stderr: "pipe",
    },
});
