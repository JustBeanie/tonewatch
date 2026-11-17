import { useEffect, useRef, useState, useSyncExternalStore } from "react";
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
    private stopped = true;
    private retryTimer: number | undefined;
    private status: ConnectionStatus = "connecting";

    connect(): void {
        if (!this.stopped) return;
        this.stopped = false;
        this.open();
    }
    subscribe(topic: string): void {
        this.topics.add(topic);
        this.sendTopics();
    }
    unsubscribe(topic: string): void {
        this.topics.delete(topic);
        this.sendTopics();
    }
    onMessage(listener: (message: WsMessage) => void): () => void {
        this.listeners.add(listener);
        return () => this.listeners.delete(listener);
    }
    onStatus(listener: (status: ConnectionStatus) => void): () => void {
        this.statusListeners.add(listener);
        return () => this.statusListeners.delete(listener);
    }
    getStatus = (): ConnectionStatus => this.status;

    close(): void {
        this.stopped = true;
        window.clearTimeout(this.retryTimer);
        this.retryTimer = undefined;
        this.retry = 0;
        const socket = this.socket;
        this.socket = undefined;
        socket?.close();
        this.setStatus("disconnected");
    }
    private setStatus(status: ConnectionStatus): void {
        this.status = status;
        this.statusListeners.forEach((listener) => listener(status));
    }
    private sendTopics(): void {
        const socket = this.socket;
        if (socket && this.status === "connected" && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "subscribe", topics: [...this.topics] }));
        }
    }
    private open(): void {
        if (this.stopped) return;
        this.setStatus("connecting");
        const socket = new WebSocket(websocketUrl());
        this.socket = socket;
        socket.onopen = () => {
            if (this.socket !== socket) return;
            this.retry = 0;
            this.setStatus("connected");
            if (this.topics.size) this.sendTopics();
        };
        socket.onmessage = (event) => {
            if (this.socket !== socket) return;
            let message: WsMessage;
            try {
                message = JSON.parse(String(event.data)) as WsMessage;
            } catch {
                return;
            }
            if (typeof message?.type !== "string") return;
            if (message.type === "ping") {
                if (socket.readyState === WebSocket.OPEN) socket.send('{"type":"pong"}');
                return;
            }
            if (message.type === "subscribed") return;
            this.listeners.forEach((listener) => listener(message));
        };
        socket.onclose = () => {
            if (this.socket !== socket) return;
            this.socket = undefined;
            this.setStatus("disconnected");
            if (!this.stopped) {
                const delay = Math.min(1000 * 2 ** this.retry++, 10000);
                this.retryTimer = window.setTimeout(() => this.open(), delay);
            }
        };
    }
}

const sharedSocket = new ToneWatchSocket();
const topicUsers = new Map<string, number>();
let consumers = 0;

function retainSocket(): () => void {
    if (++consumers === 1) sharedSocket.connect();
    return () => {
        if (--consumers === 0) sharedSocket.close();
    };
}

function messageTopic(message: WsMessage): string {
    if (message.type === "ChannelLevel" || message.type === "LevelUpdate") return "levels";
    if (message.type === "SpectrumUpdate")
        return `spectrum:${String(message.data?.source_id ?? "")}`;
    return "events";
}

function listen(topics: Set<string>, handler: (message: WsMessage) => void): () => void {
    const removeMessage = sharedSocket.onMessage((message) => {
        if (topics.has(messageTopic(message))) handler(message);
    });
    for (const topic of topics) {
        const previous = topicUsers.get(topic) ?? 0;
        topicUsers.set(topic, previous + 1);
        if (!previous) sharedSocket.subscribe(topic);
    }
    const release = retainSocket();
    return () => {
        removeMessage();
        for (const topic of topics) {
            const remaining = (topicUsers.get(topic) ?? 1) - 1;
            if (remaining) topicUsers.set(topic, remaining);
            else {
                topicUsers.delete(topic);
                sharedSocket.unsubscribe(topic);
            }
        }
        release();
    };
}

export function useSubscription(topic: string | string[]): WsMessage | undefined {
    const [message, setMessage] = useState<WsMessage>();
    useWsEvents(topic, setMessage);
    return message;
}

export function useWsEvents(topic: string | string[], handler: (message: WsMessage) => void): void {
    const handlerRef = useRef(handler);
    handlerRef.current = handler;
    const topicKey = Array.isArray(topic) ? topic.join("\u0000") : topic;
    useEffect(() => {
        if (!topicKey) return;
        return listen(new Set(topicKey.split("\u0000")), (message) => handlerRef.current(message));
    }, [topicKey]);
}

function subscribeStatus(listener: () => void): () => void {
    const remove = sharedSocket.onStatus(listener);
    const release = retainSocket();
    return () => {
        remove();
        release();
    };
}

export function useConnectionStatus(): ConnectionStatus {
    return useSyncExternalStore(subscribeStatus, sharedSocket.getStatus);
}
