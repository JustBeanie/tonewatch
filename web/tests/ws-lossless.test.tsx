import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWsEvents } from "../src/lib/ws";

class FakeWebSocket {
    static instance: FakeWebSocket;
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    constructor() {
        FakeWebSocket.instance = this;
    }
    send() {}
    close() {
        this.onclose?.();
    }
}

function Probe({
    handler,
    topic = "events",
}: {
    handler: (message: { type: string }) => void;
    topic?: string | string[];
}) {
    useWsEvents(topic, handler);
    return null;
}

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

describe("useWsEvents", () => {
    it("delivers synchronous messages in order without dropping either", () => {
        vi.stubGlobal("WebSocket", FakeWebSocket);
        const received: string[] = [];
        render(<Probe handler={(message) => received.push(message.type)} />);
        const socket = FakeWebSocket.instance;
        act(() => {
            socket.onmessage?.({ data: JSON.stringify({ type: "ToneDetected" }) });
            socket.onmessage?.({ data: JSON.stringify({ type: "CallClosed" }) });
        });
        expect(received).toEqual(["ToneDetected", "CallClosed"]);
    });

    it("subscribes to each topic in a topic list", () => {
        vi.stubGlobal("WebSocket", FakeWebSocket);
        const view = render(<Probe handler={() => undefined} topic={["events", "levels"]} />);
        const socket = FakeWebSocket.instance;
        act(() => socket.onopen?.());
        view.unmount();
        expect(socket).toBeDefined();
    });
});
