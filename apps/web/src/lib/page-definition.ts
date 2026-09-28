import { useQuery } from "@tanstack/vue-query";
import { computed, toValue } from "vue";

import { getPageDefinition } from "@soymutdb/api-client";
import type { PageComponentNode } from "@soymutdb/shared";

/**
 * Published page definitions for the routes the portal renders from the CMS.
 *
 * The React portal drove **one band** of the home page from the published
 * definition: the 资源导览 / resource-cards block
 * (`d3904c2105f34e5d74f3ae3a163d6b25f075bf64:apps/web/src/routes/index.tsx`
 * passes `findResourceCards(definition.root)` into `AntdHome`). This module
 * ports exactly that contract instead of a general page builder: the portal's
 * layout stays code-defined, and the CMS owns the card content.
 *
 * A missing definition (404) or a definition without the node is **not an
 * error**: the caller keeps rendering the built-in band, which is the product's
 * own default rather than demo data.
 */

/** One card inside a `resource_cards` node, as stored by the page builder. */
export interface ResourceCard {
  title?: unknown;
  description?: unknown;
  image_url?: unknown;
  href?: unknown;
}

export interface ResourceCardsProps {
  heading: string;
  cards: ResourceCard[];
}

/** Reject script-like values before they can reach the DOM (React parity). */
export function isScriptLike(value: unknown): boolean {
  return /javascript\s*:/i.test(String(value));
}

/**
 * Whether a stored string is safe to place in `href`.
 *
 * Ported from the React renderer's `isSafeHref`: internal `/` routes and
 * `http(s)`/`mailto`/`tel` survive, protocol-relative `//host` and every other
 * scheme-like value is dropped, and backslashes are rejected because browsers
 * normalise them into path separators.
 */
export function isSafePageHref(value: unknown): value is string {
  if (typeof value !== "string") return false;
  if (isScriptLike(value)) return false;
  if (value.startsWith("//") || /^[a-z][a-z0-9+.-]*:/i.test(value) || value.includes("\\")) {
    if (!/^(https?:|mailto:|tel:)/i.test(value)) return false;
  }
  return value.startsWith("/") || /^(https?:|mailto:|tel:)/i.test(value);
}

/** Depth-first search for the `resource_cards` node (React `findResourceCards`). */
export function findResourceCards(node: PageComponentNode | undefined): ResourceCardsProps | null {
  if (!node || typeof node !== "object") return null;
  if (node.type === "resource_cards") {
    const props = (node.props ?? {}) as { heading?: unknown; cards?: unknown };
    return {
      heading: typeof props.heading === "string" ? props.heading : "",
      cards: Array.isArray(props.cards) ? (props.cards as ResourceCard[]) : [],
    };
  }
  for (const child of node.children ?? []) {
    const match = findResourceCards(child);
    if (match) return match;
  }
  return null;
}

/**
 * Read the published definition for one route.
 *
 * Page definitions are not variant-specific in the API contract, so the key
 * carries only the route. `retry: false` keeps a 404 (no published definition)
 * from turning into three delayed attempts on every home-page load.
 */
export function usePageDefinition(route = "/") {
  const query = useQuery({
    queryKey: ["soymutdb", "page-definition", route],
    queryFn: () => getPageDefinition(route),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const resourceCards = computed(() => {
    const payload = toValue(query.data);
    return findResourceCards(payload?.definition?.root);
  });

  return {
    /** The resource-cards band the CMS publishes for this route, if any. */
    resourceCards,
    isLoading: computed(() => toValue(query.isPending)),
    isError: computed(() => toValue(query.isError)),
  };
}
