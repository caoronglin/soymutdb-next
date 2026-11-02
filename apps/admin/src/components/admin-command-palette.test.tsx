/**
 * Regression cover for the ⌘K command palette.
 *
 * Two defects this file pins down, both of which shipped green:
 *
 *  1. Every string the palette rendered was a hardcoded English literal, so the
 *     surface was fully untranslated in a zh console -- even though the bundles
 *     already carried `admin.shell.commandPlaceholder` / `commandEmpty` /
 *     `commandGeneUnavailable` / `commandHint` for exactly these lines and no
 *     code read them. `scripts/check_visible_i18n_react.mjs` scans `apps/web`
 *     only, and the locale purity test checks key parity plus bilingual
 *     literals, so neither guard could see a missing `t()` call.
 *  2. The palette takes focus on open and never gives it back. Closing it left
 *     focus on `<body>`, so a keyboard operator lost their place in the console.
 */
import * as React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * A `t` with i18next's stable identity that echoes the key back.
 *
 * The shared `mockTranslation` returns `defaultValue`, which is right for tests
 * that assert copy but wrong here: this file's first claim is that the palette
 * renders *locale keys* rather than literals, and an echo makes that visible in
 * the DOM. Identity is a module-level constant for the reason
 * `src/test/mocks.ts` documents.
 */
const echoT = (key: string): string => key;

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: echoT,
    i18n: { language: "en", changeLanguage: async () => undefined },
    ready: true,
  }),
  Trans: ({ children }: { children?: unknown }) => children,
  initReactI18next: { type: "3rdParty", init: () => undefined },
}));

const genes = vi.hoisted(() => ({ items: [] as Array<Record<string, unknown>>, fail: false }));
vi.mock("@soymutdb/api-client", () => ({
  searchGenes: async () => {
    if (genes.fail) throw new Error("gene search is down");
    return { items: genes.items };
  },
}));

import { AdminCommandPalette, COMMANDS, type AdminCommandPath } from "./admin-command-palette";

// The admin app compiles TSX with the classic React.createElement factory
// (tsconfig sets jsx: "preserve") and its component modules deliberately do
// not import React, so the identifier must exist globally before first render.
(globalThis as unknown as { React: unknown }).React = React;

afterEach(() => {
  cleanup();
  genes.items = [];
  genes.fail = false;
});

function renderPalette(overrides: Partial<{ open: boolean }> = {}) {
  const onNavigate = vi.fn();
  const onOpenGene = vi.fn();
  const view = render(
    <AdminCommandPalette
      onClose={vi.fn()}
      onNavigate={onNavigate}
      onOpenGene={onOpenGene}
      open={overrides.open ?? true}
    />,
  );
  return { ...view, onNavigate, onOpenGene };
}

describe("command palette copy is translated", () => {
  beforeEach(() => {
    genes.items = [];
  });

  it("labels the dialog, the field and the list through locale keys", () => {
    renderPalette();

    expect(screen.getByRole("dialog").getAttribute("aria-label")).toBe(
      "admin.commandPalette.dialogLabel",
    );
    expect(screen.getByRole("combobox").getAttribute("aria-label")).toBe(
      "admin.commandPalette.inputLabel",
    );
    expect(screen.getByRole("listbox").getAttribute("aria-label")).toBe(
      "admin.commandPalette.listLabel",
    );
  });

  it("renders every command row from its locale key pair", () => {
    renderPalette();

    for (const command of COMMANDS) {
      expect(screen.getByText(command.labelKey), command.id).toBeTruthy();
      expect(screen.getByText(command.hintKey), command.id).toBeTruthy();
    }
  });

  it("renders the hint and empty state through the keys the bundles already had", async () => {
    renderPalette();
    // `admin.shell.command*` existed in both bundles with no reader; the palette
    // now uses them instead of restating the copy inline.
    expect(screen.getByText("admin.shell.commandHint")).toBeTruthy();
    expect(screen.getByPlaceholderText("admin.shell.commandPlaceholder")).toBeTruthy();

    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "nothing-matches-this" } });
    expect(await screen.findByText("admin.shell.commandEmpty")).toBeTruthy();
  });

  it("keeps command search usable when the gene lookup fails", async () => {
    genes.fail = true;
    renderPalette();

    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "BRCA1" } });
    expect(await screen.findByText("admin.shell.commandGeneUnavailable")).toBeTruthy();
  });
});

describe("command palette keyboard and focus", () => {
  it("moves the active option with the arrow keys and runs it with Enter", async () => {
    const { onNavigate } = renderPalette();
    const input = screen.getByRole("combobox");

    await waitFor(() => expect(document.activeElement).toBe(input));
    expect(input.getAttribute("aria-activedescendant")).toBe("admin-command-" + COMMANDS[0].id);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    expect(input.getAttribute("aria-activedescendant")).toBe("admin-command-" + COMMANDS[1].id);

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(input.getAttribute("aria-activedescendant")).toBe("admin-command-" + COMMANDS[0].id);

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith(COMMANDS[0].path as AdminCommandPath);
  });

  it("closes on Escape and hands focus back to the element that opened it", async () => {
    function Harness() {
      const [open, setOpen] = React.useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>
            Open commands
          </button>
          <AdminCommandPalette
            onClose={() => setOpen(false)}
            onNavigate={() => undefined}
            onOpenGene={() => undefined}
            open={open}
          />
        </>
      );
    }

    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open commands" });
    trigger.focus();
    trigger.click();

    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

    // The palette unmounts, so the input goes with it; focus must not be left
    // stranded on <body>.
    await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });
});
