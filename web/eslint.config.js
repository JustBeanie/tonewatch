import tseslint from "@typescript-eslint/eslint-plugin";
import parser from "@typescript-eslint/parser";
import react from "eslint-plugin-react";
import hooks from "eslint-plugin-react-hooks";
export default [
    {
        ignores: [
            "dist",
            "e2e/**",
            "playwright.config.ts",
            "coverage",
            "vite.config.ts",
            "vitest.config.ts",
            "*.d.ts",
            "*.js",
            "src/api/generated/**",
            "src/api/openapi.json",
            "src/api/ws-messages.ts",
        ],
    },
    {
        files: ["**/*.{ts,tsx}"],
        languageOptions: {
            parser,
            parserOptions: { project: "./tsconfig.app.json", tsconfigRootDir: import.meta.dirname },
        },
        plugins: { "@typescript-eslint": tseslint, react, "react-hooks": hooks },
        rules: {
            "@typescript-eslint/no-explicit-any": "error",
            "@typescript-eslint/no-unused-vars": "error",
            "react/jsx-uses-react": "error",
            "react/react-in-jsx-scope": "off",
        },
        settings: { react: { version: "detect" } },
    },
];
