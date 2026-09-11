import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useAdminShellShortcuts } from "./use-admin-shell-shortcuts";

function Harness({ onOpenCommandPalette, onToggleSidebar }: { onOpenCommandPalette: () => void; onToggleSidebar: () => void }) {
  useAdminShellShortcuts({ onOpenCommandPalette, onToggleSidebar });
  return <input aria-label="Editable field" />;
}

function keydown(target: EventTarget, init: KeyboardEventInit) {
  const event = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

describe("useAdminShellShortcuts", () => {
  it("opens the command palette with Cmd/Ctrl+K", () => {
    const onOpenCommandPalette = vi.fn();
    render(<Harness onOpenCommandPalette={onOpenCommandPalette} onToggleSidebar={vi.fn()} />);

    const event = keydown(window, { key: "k", ctrlKey: true });

    expect(onOpenCommandPalette).toHaveBeenCalledOnce();
    expect(event.defaultPrevented).toBe(true);
  });

  it("toggles the sidebar with B outside editable controls", () => {
    const onToggleSidebar = vi.fn();
    const { container } = render(<Harness onOpenCommandPalette={vi.fn()} onToggleSidebar={onToggleSidebar} />);

    const event = keydown(container, { key: "b" });

    expect(onToggleSidebar).toHaveBeenCalledOnce();
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not capture B in text controls or modified browser shortcuts", () => {
    const onToggleSidebar = vi.fn();
    const { getByRole } = render(<Harness onOpenCommandPalette={vi.fn()} onToggleSidebar={onToggleSidebar} />);

    const input = getByRole("textbox", { name: "Editable field" });
    const typingEvent = keydown(input, { key: "b" });
    const browserEvent = keydown(window, { key: "b", ctrlKey: true });

    expect(onToggleSidebar).not.toHaveBeenCalled();
    expect(typingEvent.defaultPrevented).toBe(false);
    expect(browserEvent.defaultPrevented).toBe(false);
  });
});
