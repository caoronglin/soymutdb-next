/** Bounded undo/redo history for the Admin Page Builder draft. */

import type { PageDefinitionV2 } from "@soymutdb/shared";

export interface PageBuilderHistory {
  past: PageDefinitionV2[];
  future: PageDefinitionV2[];
}

const MAX_HISTORY = 50;

export function emptyHistory(): PageBuilderHistory {
  return { past: [], future: [] };
}

export function pushHistory(
  history: PageBuilderHistory,
  current: PageDefinitionV2,
  next: PageDefinitionV2,
): PageBuilderHistory {
  if (JSON.stringify(current) === JSON.stringify(next)) return history;
  return {
    past: [...history.past, current].slice(-MAX_HISTORY),
    future: [],
  };
}

export function undoHistory(
  history: PageBuilderHistory,
  current: PageDefinitionV2,
): { history: PageBuilderHistory; draft: PageDefinitionV2 } | null {
  const previous = history.past.at(-1);
  if (!previous) return null;
  return {
    history: {
      past: history.past.slice(0, -1),
      future: [current, ...history.future],
    },
    draft: previous,
  };
}

export function redoHistory(
  history: PageBuilderHistory,
  current: PageDefinitionV2,
): { history: PageBuilderHistory; draft: PageDefinitionV2 } | null {
  const next = history.future[0];
  if (!next) return null;
  return {
    history: {
      past: [...history.past, current],
      future: history.future.slice(1),
    },
    draft: next,
  };
}
