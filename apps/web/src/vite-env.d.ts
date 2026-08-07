/// <reference types="vite/client" />

// Web Worker module declarations — allow `import WorkerUrl from './foo.worker.ts?worker'`
declare module '*.worker.ts?worker' {
    const WorkerConstructor: { new (): Worker };
    export default WorkerConstructor;
}
declare module '*.worker?worker' {
    const WorkerConstructor: { new (): Worker };
    export default WorkerConstructor;
}

// View Transitions API (not yet in lib.dom for all TS versions).
interface ViewTransition {
    finished: Promise<void>;
    ready: Promise<void>;
    updateCallbackDone: Promise<void>;
    skipTransition(): void;
}

interface Document {
    startViewTransition?(updateCallback: () => Promise<void> | void): ViewTransition;
}

// Network Information API (partial, for saveData).
interface NetworkInformation {
    readonly saveData?: boolean;
    readonly effectiveType?: string;
    readonly downlink?: number;
}
interface Navigator {
    readonly connection?: NetworkInformation;
}
