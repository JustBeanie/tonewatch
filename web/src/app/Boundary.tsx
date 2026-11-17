import { Component, type ReactNode } from "react";

type Props = { children: ReactNode; fallback?: ReactNode };

export class Boundary extends Component<Props, { failed: boolean }> {
    override state = { failed: false };

    static getDerivedStateFromError() {
        return { failed: true };
    }

    override render() {
        if (this.state.failed) {
            return (
                this.props.fallback ?? (
                    <main className="content">
                        <p role="alert">This page could not load.</p>
                        <button type="button" onClick={() => window.location.reload()}>
                            Reload page
                        </button>
                    </main>
                )
            );
        }
        return this.props.children;
    }
}
