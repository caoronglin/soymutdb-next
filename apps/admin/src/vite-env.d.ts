/// <reference types="vite/client" />

// View Transitions API types.
interface ViewTransition {
    finished: Promise<void>;
    ready: Promise<void>;
    updateCallbackDone: Promise<void>;
    skipTransition(): void;
}
interface Document {
    startViewTransition?(updateCallback: () => Promise<void> | void): ViewTransition;
}
interface NetworkInformation {
    readonly saveData?: boolean;
    readonly effectiveType?: string;
}
interface Navigator {
    readonly connection?: NetworkInformation;
}
