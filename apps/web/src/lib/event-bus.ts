/**
 * Typed Event Bus — tiny (~20 line) pub/sub for decoupled widget communication.
 *
 * Widgets and services communicate through named events rather than importing
 * each other directly, keeping the widget system loosely coupled. Payloads are
 * fully typed via the `EventMap` generic; untyped events fall back to `unknown`.
 *
 * Usage:
 *   bus.on('widget:loaded', (name) => console.log(name));
 *   bus.emit('widget:loaded', 'gene-card');
 *   bus.off('widget:loaded', handler);
 */
export type EventHandler<T = unknown> = (payload: T) => void;

type GlobalEventMap = {
    'widget:loaded': string;
    'widget:error': { name: string; error: string };
    'search:filter': { query: string; total: number };
    'theme:change': 'light' | 'dark';
    'i18n:change': string;
    'analytics:track': { event: string; props?: Record<string, unknown> };
};

export class EventBus<EventMap extends Record<string, unknown> = GlobalEventMap> {
    private listeners = new Map<string, Set<EventHandler<unknown>>>();

    on<K extends keyof EventMap & string>(event: K, handler: EventHandler<EventMap[K]>): () => void {
        let set = this.listeners.get(event);
        if (!set) {
            set = new Set();
            this.listeners.set(event, set);
        }
        set.add(handler as EventHandler<unknown>);
        return () => this.off(event, handler);
    }

    off<K extends keyof EventMap & string>(event: K, handler: EventHandler<EventMap[K]>): void {
        this.listeners.get(event)?.delete(handler as EventHandler<unknown>);
    }

    emit<K extends keyof EventMap & string>(event: K, payload: EventMap[K]): void {
        // Also dispatch on document.body so non-TS consumers / custom elements
        // can listen via addEventListener('widget:loaded', ...).
        if (typeof document !== "undefined") {
            document.body.dispatchEvent(
                new CustomEvent(event, { detail: payload, bubbles: true }),
            );
        }
        const set = this.listeners.get(event);
        if (!set) return;
        for (const handler of set) {
            try {
                handler(payload);
            } catch (err) {
                console.error(`[event-bus] handler for "${event}" threw:`, err);
            }
        }
    }

    once<K extends keyof EventMap & string>(event: K, handler: EventHandler<EventMap[K]>): () => void {
        const wrapped: EventHandler<EventMap[K]> = (payload) => {
            this.off(event, wrapped);
            handler(payload);
        };
        return this.on(event, wrapped);
    }
}

/** Global singleton — import this everywhere rather than creating new buses. */
export const bus = new EventBus();
