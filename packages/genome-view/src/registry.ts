import type { Component } from "vue";

/** A renderer bound to a backend track `type`. */
export interface TrackRendererDescriptor {
  /** Vue component that renders a single `TrackConfig`. */
  component: Component;
  /** Capability required before this renderer may be offered to the user. */
  requiredCapability?: string;
}

const renderers = new Map<string, TrackRendererDescriptor>();

/** Register a renderer for a backend track `type`; duplicate types throw. */
export function registerTrackRenderer(type: string, descriptor: TrackRendererDescriptor): void {
  if (!type) {
    throw new Error("registerTrackRenderer: track type must be a non-empty string");
  }
  if (renderers.has(type)) {
    throw new Error(`registerTrackRenderer: duplicate renderer for track type "${type}"`);
  }
  renderers.set(type, descriptor);
}

/** Resolve the renderer registered for `type`, or `undefined` when unknown. */
export function resolveTrackRenderer(type: string): TrackRendererDescriptor | undefined {
  return renderers.get(type);
}

/** Registered track type names, in registration order. */
export function listTrackRenderers(): string[] {
  return [...renderers.keys()];
}
