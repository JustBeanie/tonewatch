import { BrowserRouter } from "react-router";
import { Router } from "./app/router";
import "./styles.css";

function basePath(): string | undefined {
    const href = document.querySelector("base")?.getAttribute("href");
    if (!href) return undefined;
    const path = new URL(href, window.location.href).pathname.replace(/\/$/, "");
    return path || undefined;
}

export function App() {
    const basename = basePath();
    return (
        <BrowserRouter {...(basename ? { basename } : {})}>
            <Router />
        </BrowserRouter>
    );
}
