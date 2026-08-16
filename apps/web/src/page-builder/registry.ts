/**
 * Public component registry (Phase 4).
 *
 * The exhaustive set of allowlisted component `type` keys. The concrete React
 * adapters for each key live in renderer.tsx; every allowlisted key MUST have
 * a registered adapter there (asserted by the renderer test and a build guard).
 */
import { COMPONENT_TYPE_KEYS, type ComponentTypeKey, type PageComponent } from "./types";

/** Exhaustive set of the allowed component type keys. */
export const REGISTERED_COMPONENT_TYPES: ReadonlySet<ComponentTypeKey> = new Set(
  COMPONENT_TYPE_KEYS,
);

/** True when the node's `type` is an allowlisted component key. */
export function hasRendererFor(value: unknown): value is PageComponent {
  if (!value || typeof value !== "object") return false;
  const type = (value as { type?: unknown }).type;
  return typeof type === "string" && (REGISTERED_COMPONENT_TYPES as ReadonlySet<string>).has(type);
}

/** Resolve a node to a component type key, or null for an unknown type. */
export function componentTypeOf(node: PageComponent): ComponentTypeKey | null {
  return REGISTERED_COMPONENT_TYPES.has(node.type) ? node.type : null;
}
