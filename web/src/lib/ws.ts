import { useEffect, useState } from "react";
import { websocketUrl } from "./urls";

export type WsMessage = { type: string; data?: Record<string, unknown> };
type SocketLike = WebSocket;
export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export class ToneWatchSocket {
    private socket: SocketLike | undefined;
    private topics = new Set<string>();
    private listeners = new Set<(message: WsMessage) => void>();
    private statusListeners = new Set<(status: ConnectionStatus) => void>();
    private retry = 0;
    private stopped = false;
    private connected = false;

    connect(): void {
        this.stopped = false;
        this.open();
    }
    subscribe(topic: string): void {
        this.topics.add(topic);
        if (this.connected)
            this.socket?.send(JSON.stringify({ type: "subscribe", topics: [...this.topics] }));
    }
    unsubscribe(topic: string): void {
        this.topics.delete(topic);
        if (this.connected)
            this.socket?.send(JSON.stringify({ type: "subscribe", topics: [...this.topics] }));
    }
    onMessage(listener: (message: WsMessage) => void): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }
    onStatus(listener: (status: ConnectionStatus) => void): () => void {
        this.statusListeners.add(listener);
        return () => this.statusListeners.delete(listener);
    }
    close(): void {
        this.stopped = true;
        this.connected = false;
        this.socket?.close();
    }
    private open(): void {
        if (this.stopped) return;
        this.statusListeners.forEach((listener) => listener("connecting"));
        const socket = new WebSocket(websocketUrl());
        this.socket = socket;
        socket.onopen = () => {
            this.connected = true;
            this.statusListeners.forEach((listener) => listener("connected"));
            this.retry = 0;
            if (this.topics.size)
                socket.send(JSON.stringify({ type: "subscribe", topics: [...this.topics] }));
        };
        socket.onmessage = (event) => {
            const message = JSON.parse(String(event.data)) as WsMessage;
            this.listeners.forEach((listener) => listener(message));
        };
        socket.onclose = () => {
            this.connected = false;
            this.statusListeners.forEach((listener) => listener("disconnected"));
            if (!this.stopped) {
                const delay = Math.min(1000 * 2 ** this.retry++, 10000);
                window.setTimeout(() => this.open(), delay);
            }
        };
    }
}

export function useSubscription(topic: string | string[]): WsMessage | undefined {
    const [message, setMessage] = useState<WsMessage>();
    useEffect(() => {
        const socket = new ToneWatchSocket();
        socket.connect();
        const remove = socket.onMessage(setMessage);
        const topics = Array.isArray(topic) ? topic : [topic];
        topics.forEach((item) => socket.subscribe(item));
        return () => {
            remove();
            topics.forEach((item) => socket.unsubscribe(item));
            socket.close();
        };
    }, [topic]);
    return message;
}

export function useConnectionStatus(): ConnectionStatus {
    const [status, setStatus] = useState<ConnectionStatus>("connecting");
    useEffect(() => {
        const socket = new ToneWatchSocket();
        const remove = socket.onStatus(setStatus);
        socket.connect();
        return () => {
            remove();
            socket.close();
        };
    }, []);
    return status;
}
