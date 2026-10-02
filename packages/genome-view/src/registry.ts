import type { ComponentType } from "react";

/** A renderer bound to a backend track `type`. */
export interface TrackRendererDescriptor {
  /** React component that renders a single `TrackConfig`. */
  component: ComponentType<TrackRendererProps>;
  /** Capability required before this renderer may be offered to the user. */
  requiredCapability?: string;
}

/** Props every track renderer receives. */
export interface TrackRendererProps {
  /** Track identity from the backend configuration. */
  trackId: string;
  /** Human-readable label for the track. */
  label: string;
  /** Renderer-specific payload; shape is owned by the renderer. */
  data?: unknown;
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

/** Test-only: drop every registration so a suite can re-register cleanly. */
export function resetTrackRenderers(): void {
  renderers.clear();
}
