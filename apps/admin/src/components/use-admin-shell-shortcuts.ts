import { useEffect } from "react";

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * Provides non-destructive admin-shell shortcuts without intercepting typing
 * or browser-reserved key combinations.
 */
export function useAdminShellShortcuts({
  onOpenCommandPalette,
  onToggleSidebar,
}: {
  onOpenCommandPalette: () => void;
  onToggleSidebar?: () => void;
}) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();

      if ((event.metaKey || event.ctrlKey) && key === "k") {
        event.preventDefault();
        onOpenCommandPalette();
        return;
      }

      if (
        key === "b" &&
        !event.metaKey &&
        !event.ctrlKey &&
        !event.altKey &&
        !event.shiftKey &&
        !isEditableTarget(event.target)
      ) {
        event.preventDefault();
        onToggleSidebar?.();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onOpenCommandPalette, onToggleSidebar]);
}
