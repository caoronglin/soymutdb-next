/**
 * Dependency Injection — ServiceRegistry for lazy service registration.
 *
 * Services (api client, analytics, i18n, theme, etc.) are registered with a
 * factory function the first time they are requested, avoiding eager imports
 * and allowing widgets to depend on abstractions rather than concrete modules.
 *
 * Usage:
 *   registry.register('api', () => createApiClient());
 *   const api = registry.get('api');  // instantiated lazily on first call
 */
type Factory<T> = () => T;

export class ServiceRegistry {
    private factories = new Map<string, Factory<unknown>>();
    private instances = new Map<string, unknown>();

    /** Register a service factory. Overwrites any previous registration for `token`. */
    register<T>(token: string, factory: Factory<T>): void {
        this.factories.set(token, factory as Factory<unknown>);
        // Invalidate previously cached instance so the new factory is used.
        this.instances.delete(token);
    }

    /** Retrieve (or lazily create) a service. Throws if token was never registered. */
    get<T>(token: string): T {
        if (this.instances.has(token)) {
            return this.instances.get(token) as T;
        }
        const factory = this.factories.get(token);
        if (!factory) {
            throw new Error(`[di] Service "${token}" not registered. Did you forget to register it?`);
        }
        const instance = factory();
        this.instances.set(token, instance);
        return instance as T;
    }

    /** Check if a service has been registered (does not instantiate it). */
    has(token: string): boolean {
        return this.factories.has(token);
    }

    /** Force a fresh instantiation on next `get()` (useful in tests / hot reload). */
    evict(token: string): void {
        this.instances.delete(token);
    }

    /** Remove all registrations (test utility). */
    clear(): void {
        this.factories.clear();
        this.instances.clear();
    }
}

/** Global DI container. */
export const registry = new ServiceRegistry();

/* ------------------------------------------------------------------ */
/*  Well-known service tokens                                         */
/* ------------------------------------------------------------------ */

export const SERVICES = {
    API: 'api',
    ANALYTICS: 'analytics',
    I18N: 'i18n',
    THEME: 'theme',
    EVENT_BUS: 'event-bus',
} as const;
