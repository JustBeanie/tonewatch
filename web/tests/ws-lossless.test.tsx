import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useWsEvents } from "../src/lib/ws";

class FakeWebSocket {
    static OPEN = 1;
    static instance: FakeWebSocket;
    static instances: FakeWebSocket[] = [];
    readyState = 1;
    sent: unknown[] = [];
    onopen: (() => void) | null = null;
    onmessage: ((event: { data: string }) => void) | null = null;
    onclose: (() => void) | null = null;
    constructor() {
        FakeWebSocket.instance = this;
        FakeWebSocket.instances.push(this);
    }
    send(message: string) {
        this.sent.push(JSON.parse(message));
    }
    emit(type: string, data?: Record<string, unknown>) {
        this.onmessage?.({ data: JSON.stringify({ type, data }) });
    }
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
    vi.useRealTimers();
    FakeWebSocket.instances = [];
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

    it("shares topics, keeps heartbeat traffic internal, and cancels the last reconnect", () => {
        vi.stubGlobal("WebSocket", FakeWebSocket);
        vi.useFakeTimers();
        const events = vi.fn();
        const levels = vi.fn();
        const view = render(
            <>
                <Probe handler={events} />
                <Probe handler={levels} topic="levels" />
            </>,
        );
        expect(FakeWebSocket.instances).toHaveLength(1);
        const first = FakeWebSocket.instance;
        act(() => {
            first.onopen?.();
            first.emit("ping");
            first.emit("subscribed");
            first.emit("ChannelLevel", { dbfs: -45 });
            first.emit("CallClosed");
        });
        expect(first.sent).toEqual([
            { type: "subscribe", topics: ["events", "levels"] },
            { type: "pong" },
        ]);
        expect(events.mock.calls.map(([message]) => message.type)).toEqual(["CallClosed"]);
        expect(levels.mock.calls.map(([message]) => message.type)).toEqual(["ChannelLevel"]);
        act(() => {
            first.close();
            vi.advanceTimersByTime(1000);
        });
        const second = FakeWebSocket.instance;
        expect(second).not.toBe(first);
        act(() => second.onopen?.());
        expect(second.sent[0]).toEqual({ type: "subscribe", topics: ["events", "levels"] });
        act(() => second.close());
        view.unmount();
        expect(vi.getTimerCount()).toBe(0);
        vi.advanceTimersByTime(10_000);
        expect(FakeWebSocket.instances).toHaveLength(2);
    });
});
