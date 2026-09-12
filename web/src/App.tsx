import { BrowserRouter } from "react-router";
import { Router } from "./app/router";
import "./styles.css";

export function App() {
    return (
        <BrowserRouter>
            <Router />
        </BrowserRouter>
    );
}
