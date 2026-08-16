/**
 * Public component registry (Phase 8).
 *
 * The exhaustive set of allowlisted component renderer keys (snake_case, in
 * sync with `apps/api/app/page_builder/registry.py`). Concrete React adapters
 * for each key live in renderer.tsx; every allowlisted key MUST have an
 * adapter there (asserted by the renderer test).
 */
import { COMPONENT_TYPE_KEYS, type ComponentTypeKey, type PageComponentNode } from "./types";

/** Exhaustive set of allowable renderer keys. */
export const REGISTERED_COMPONENT_TYPES: ReadonlySet<ComponentTypeKey> = new Set(
  COMPONENT_TYPE_KEYS,
);

/** True when a node's `type` is an allowlisted renderer key. */
export function hasRendererFor(value: unknown): value is PageComponentNode {
  if (!value || typeof value !== "object") return false;
  const type = (value as { type?: unknown }).type;
  return typeof type === "string" && (REGISTERED_COMPONENT_TYPES as ReadonlySet<string>).has(type);
}

/** Resolve a node to a component type key, or null for an unknown type. */
export function componentTypeOf(node: PageComponentNode): ComponentTypeKey | null {
  return REGISTERED_COMPONENT_TYPES.has(node.type) ? node.type : null;
}
