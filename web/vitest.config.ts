import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    test: {
        exclude: ["**/node_modules/**", "**/dist/**", "e2e/**"],
        environment: "jsdom",
        setupFiles: "./tests/setup.ts",
        coverage: { thresholds: { lines: 80, functions: 80, statements: 80, branches: 80 } },
    },
});
