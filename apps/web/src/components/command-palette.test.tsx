/**
 * Regression cover for the public ⌘K command palette.
 *
 * Three defects this file pins down, all of which shipped green:
 *
 *  1. The overlay claimed `aria-modal="true"` but had no focus trap: Tab
 *     walked straight out of the palette into the header behind the backdrop.
 *  2. The palette took focus on open and never gave it back. Closing it left
 *     focus on `<body>`, so a keyboard operator lost their place on the page.
 *  3. The active row was a CSS highlight only — the field was not a combobox,
 *     there was no `aria-activedescendant`, and every row label was a
 *     hardcoded English literal even though both catalogs already carried
 *     `commandPalette.<id>.label` / `commandPalette.<id>.description`.
 *
 * The tests drive the real DOM: the focus assertions read `document.activeElement`
 * and the `aria-activedescendant` assertions resolve the referenced id, so a
 * dangling reference fails the test instead of passing on a string compare.
 */
import * as React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import { buildBaseI18nOptions } from "@soymutdb/i18n-core";

const navigate = vi.hoisted(() => vi.fn());
vi.mock("@tanstack/react-router", () => ({ useNavigate: () => navigate }));

import { CommandPalette } from "./command-palette";

beforeAll(async () => {
  // The real catalogs, not an echo of the key: the point of the copy tests
  // below is that the palette reads the shipped translations.
  await i18next.use(initReactI18next).init({
    ...buildBaseI18nOptions("en"),
    lng: "en",
  });
});

afterEach(async () => {
  cleanup();
  navigate.mockClear();
  await i18next.changeLanguage("en");
});

/** Open the palette the way the page does: the global ⌘K / Ctrl+K shortcut. */
function openPalette() {
  fireEvent.keyDown(document, { key: "k", metaKey: true });
}

function activeOptionId(): string | null {
  return screen.getByRole("combobox").getAttribute("aria-activedescendant");
}

/**
 * Harness for the focus-restore cases: the trigger and the palette are
 * mounted independently so a test can unmount either one.
 *
 * It lives at module scope on purpose — a component defined inside a
 * `describe` body would be re-created on every render and trips
 * `react/no-unstable-nested-components`.
 */
function PaletteHarness({ palette, trigger = true }: { palette: boolean; trigger?: boolean }) {
  return (
    <>
      {trigger ? (
        <button type="button">Open quick search</button>
      ) : null}
      {palette ? <CommandPalette /> : null}
    </>
  );
}

describe("command palette navigation", () => {
  it("opens the genome browser tool rather than an assembly-less viewer", async () => {
    render(<CommandPalette />);
    openPalette();

    const option = await screen.findByRole("option", { name: /Open Genome Browser/ });
    fireEvent.click(option);

    expect(navigate).toHaveBeenCalledWith({ to: "/search/gbrowse" });
  });

  it("keeps the typed query reachable through the search entry", async () => {
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    fireEvent.change(input, { target: { value: "BRCA1" } });

    // With a query the first row is the search submission, and Enter runs it.
    const searchEntry = screen.getByRole("option", { name: /Search for/i });
    expect(searchEntry.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input, { key: "Enter" });

    expect(navigate).toHaveBeenCalledWith({ to: "/search", search: { q: "BRCA1" } });
  });

  it("moves the active option with the arrow keys and runs it with Enter", async () => {
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));

    const first = activeOptionId();
    expect(first).toBeTruthy();

    fireEvent.keyDown(input, { key: "ArrowDown" });
    const second = activeOptionId();
    expect(second).not.toBe(first);
    expect(document.getElementById(second ?? "")?.getAttribute("aria-selected")).toBe("true");
    expect(document.getElementById(second ?? "")?.getAttribute("role")).toBe("option");

    fireEvent.keyDown(input, { key: "ArrowUp" });
    expect(activeOptionId()).toBe(first);

    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(navigate).toHaveBeenCalledWith({ to: "/genes" });
  });
});

describe("command palette accessibility semantics", () => {
  it("exposes the field as a combobox that owns the highlighted row", async () => {
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    expect(input.getAttribute("aria-expanded")).toBe("true");
    expect(input.getAttribute("aria-autocomplete")).toBe("list");

    const listboxId = input.getAttribute("aria-controls");
    expect(listboxId).toBeTruthy();
    const listbox = document.getElementById(listboxId ?? "");
    expect(listbox).not.toBeNull();
    expect(listbox?.getAttribute("role")).toBe("listbox");

    // `aria-activedescendant` has to name an option that really exists inside
    // the controlled listbox — a dangling id is worse than no id at all.
    const activeId = activeOptionId();
    expect(activeId).toBeTruthy();
    const active = document.getElementById(activeId ?? "");
    expect(active).not.toBeNull();
    expect(active?.getAttribute("role")).toBe("option");
    expect(active?.getAttribute("aria-selected")).toBe("true");
    expect(listbox?.contains(active ?? null)).toBe(true);
  });

  it("traps Tab and Shift+Tab inside the modal", async () => {
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));
    const close = screen.getByRole("button", { name: /Close/i });
    const dialog = screen.getByRole("dialog");

    // Tab on the last tabbable element cycles back to the first one.
    close.focus();
    fireEvent.keyDown(close, { key: "Tab" });
    expect(document.activeElement).toBe(input);

    // Shift+Tab on the first tabbable element cycles to the last one.
    fireEvent.keyDown(input, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(close);

    // Focus never leaves the modal.
    expect(dialog.contains(document.activeElement)).toBe(true);
  });

  it("announces the empty state when no quick action matches", async () => {
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    fireEvent.change(input, { target: { value: "zzz-no-such-action" } });

    const empty = await screen.findByRole("status");
    expect(empty.textContent).toContain("zzz-no-such-action");
    // The search submission stays reachable; only the action rows are gone.
    expect(screen.getAllByRole("option")).toHaveLength(1);
  });
});

describe("command palette focus handling", () => {
  function Harness({ withTrigger = true }: { withTrigger?: boolean }) {
    return (
      <>
        {withTrigger ? (
          <button type="button" onClick={openPalette}>
            Open quick search
          </button>
        ) : null}
        <CommandPalette />
      </>
    );
  }

  it("hands focus back to the trigger when Escape closes the palette", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open quick search" });
    trigger.focus();

    openPalette();
    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));

    fireEvent.keyDown(input, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("hands focus back when the backdrop dismisses the palette", async () => {
    render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open quick search" });
    trigger.focus();

    openPalette();
    await screen.findByRole("combobox");

    fireEvent.click(screen.getByRole("dialog"));

    await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("does not focus a trigger that navigation already unmounted", async () => {
    const { rerender } = render(<Harness />);
    const trigger = screen.getByRole("button", { name: "Open quick search" });
    const triggerFocus = vi.spyOn(trigger, "focus");
    trigger.focus();

    openPalette();
    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));

    // A palette action can navigate away and take the trigger with it.
    rerender(<Harness withTrigger={false} />);
    triggerFocus.mockClear();

    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());

    expect(triggerFocus).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(document.body);
  });
});

describe("command palette copy comes from the catalogs", () => {
  it("renders the quick actions from the Chinese catalog", async () => {
    await i18next.changeLanguage("zh");
    render(<CommandPalette />);
    openPalette();

    const option = await screen.findByRole("option", { name: /打开基因组浏览器/ });
    expect(option.textContent).toContain("跳转到 JBrowse 浏览器");
    // The hardcoded English copy must not survive next to the translation.
    expect(screen.queryByText("Open Genome Browser")).toBeNull();
  });

  it("keeps the English catalog copy when the locale is English", async () => {
    render(<CommandPalette />);
    openPalette();

    const option = await screen.findByRole("option", { name: /Open Genome Browser/ });
    expect(option.textContent).toContain("Navigate to the JBrowse viewer");
  });
});

/**
 * ---------------------------------------------------------------------
 * S3 follow-up lane — DOM behaviour the first review could not pin down.
 *
 * The production component is untouched; this file is the only thing written
 * here. Every assertion reads the real DOM (`document.activeElement`,
 * resolved option ids, the live result of `dispatchEvent`), so a dangling
 * `aria-activedescendant`, a focus that silently fell back to `<body>` or a
 * double navigation fails the test instead of passing on a string compare.
 *
 * Covered in this block:
 *  - selection side effects: a row click and an Enter selection each
 *    navigate exactly once, and selecting closes the palette;
 *  - focus restore on close, on unmount of the palette itself — not only
 *    when the trigger is unmounted — and the refusal to focus a trigger
 *    that is already gone;
 *  - `aria-activedescendant` under StrictMode's double render, including
 *    after the query is cleared;
 *  - the Chinese console finding rows by the English term ("blast") and by
 *    the Chinese term ("基因");
 *  - the Tab wrap being default-prevented, not merely re-focused.
 *
 * jsdom limit, stated on purpose: jsdom implements neither native Tab
 * traversal nor `:focus-visible`, so these tests can only prove that the
 * handler called `preventDefault()` and moved focus itself. The end-to-end
 * "Tab never leaves the modal" contract still needs a real browser; no
 * Playwright spec covers the palette today (`e2e/tests/` has no palette
 * case), so a green jsdom run is not a substitute for one.
 */
describe("command palette selection side effects", () => {
  it("navigates exactly once when a quick-action row is clicked", async () => {
    render(<CommandPalette />);
    openPalette();

    const option = await screen.findByRole("option", { name: /BLAST Search/ });
    fireEvent.click(option);

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith({ to: "/blast" });

    // Selecting closes the palette, and closing must not navigate again.
    await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("navigates exactly once when the active row is chosen with Enter", async () => {
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));

    fireEvent.keyDown(input, { key: "Enter" });

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith({ to: "/search/gbrowse" });

    await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("navigates exactly once when the search row is chosen with Enter", async () => {
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    fireEvent.change(input, { target: { value: "BRCA1" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith({ to: "/search", search: { q: "BRCA1" } });
  });
});

describe("command palette focus restore", () => {
  it("hands focus back to a connected trigger when the palette closes with the close button", async () => {
    render(<PaletteHarness palette />);
    const trigger = screen.getByRole("button", { name: "Open quick search" });
    trigger.focus();

    openPalette();
    await screen.findByRole("combobox");

    fireEvent.click(screen.getByRole("button", { name: /Close/i }));

    await waitFor(() => expect(screen.queryByRole("combobox")).toBeNull());
    expect(document.activeElement).toBe(trigger);
  });

  it("restores focus to a connected trigger when the palette itself unmounts", async () => {
    const { rerender } = render(<PaletteHarness palette />);
    const trigger = screen.getByRole("button", { name: "Open quick search" });
    trigger.focus();
    expect(document.activeElement).toBe(trigger);

    openPalette();
    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));

    // The palette goes away on its own (route change, parent unmount) while
    // the trigger is still on the page: focus has to come back to it.
    rerender(<PaletteHarness palette={false} />);

    await waitFor(() => expect(document.activeElement).toBe(trigger));
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("does not focus a trigger that was already unmounted when the palette unmounts", async () => {
    const { rerender } = render(<PaletteHarness palette />);
    const trigger = screen.getByRole("button", { name: "Open quick search" });
    const focusSpy = vi.spyOn(trigger, "focus");
    trigger.focus();

    openPalette();
    await screen.findByRole("combobox");

    // The trigger disappears first — navigation took it with the page.
    rerender(<PaletteHarness palette trigger={false} />);
    focusSpy.mockClear();

    // Now the palette itself unmounts. The detached trigger must be skipped.
    rerender(<PaletteHarness palette={false} trigger={false} />);

    expect(focusSpy).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(document.body);
  });
});

describe("command palette combobox under StrictMode", () => {
  it("keeps aria-activedescendant pointing at a live option, including after the query is cleared", async () => {
    render(
      <React.StrictMode>
        <CommandPalette />
      </React.StrictMode>,
    );
    openPalette();

    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));

    // StrictMode renders twice: the DOM must hold one palette, not two.
    const rows = screen.getAllByRole("option");
    expect(rows).toHaveLength(6);
    const rowIds = rows.map((row) => row.id);
    expect(new Set(rowIds).size).toBe(rowIds.length);

    const initial = input.getAttribute("aria-activedescendant");
    expect(initial).toBeTruthy();
    expect(document.getElementById(initial ?? "")?.getAttribute("role")).toBe("option");

    // A query puts the search submission on top of the action rows.
    fireEvent.change(input, { target: { value: "BRCA1" } });
    const withQuery = input.getAttribute("aria-activedescendant");
    expect(withQuery).toBeTruthy();
    expect(document.getElementById(withQuery ?? "")?.getAttribute("role")).toBe("option");

    // Clearing the query drops the search row again. The active descendant
    // has to follow it and still name an option that exists in the listbox.
    fireEvent.change(input, { target: { value: "" } });
    const cleared = input.getAttribute("aria-activedescendant");
    expect(cleared).toBeTruthy();

    const option = document.getElementById(cleared ?? "");
    expect(option).not.toBeNull();
    expect(option?.getAttribute("role")).toBe("option");
    expect(option?.getAttribute("aria-selected")).toBe("true");

    const listbox = document.getElementById(input.getAttribute("aria-controls") ?? "");
    expect(listbox?.contains(option ?? null)).toBe(true);
    expect(screen.getAllByRole("option")).toHaveLength(6);
  });
});

describe("command palette search across the language boundary", () => {
  it("finds the BLAST row from the English term in the Chinese console", async () => {
    await i18next.changeLanguage("zh");
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    fireEvent.change(input, { target: { value: "blast" } });

    const option = await screen.findByRole("option", { name: /BLAST 检索/ });
    // Only the search submission and the BLAST row survive the filter.
    expect(screen.getAllByRole("option")).toHaveLength(2);

    fireEvent.click(option);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith({ to: "/blast" });
  });

  it("finds the gene row from the Chinese term", async () => {
    await i18next.changeLanguage("zh");
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    fireEvent.change(input, { target: { value: "基因" } });

    const geneRow = await screen.findByRole("option", { name: /浏览基因/ });
    // Rows that do not mention genes are filtered out.
    expect(screen.queryByRole("option", { name: /检索变异/ })).toBeNull();
    expect(screen.queryByRole("option", { name: /下载数据/ })).toBeNull();

    fireEvent.click(geneRow);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledWith({ to: "/genes" });
  });
});

describe("command palette tab wrap contract", () => {
  it("default-prevents the wrapped Tab keydown instead of only re-focusing", async () => {
    render(<CommandPalette />);
    openPalette();

    const input = await screen.findByRole("combobox");
    await waitFor(() => expect(document.activeElement).toBe(input));
    const close = screen.getByRole("button", { name: /Close/i });

    // Tab in the middle of the list is left to the browser: `fireEvent`
    // returns `true` when nothing called `preventDefault()`.
    expect(fireEvent.keyDown(input, { key: "Tab", cancelable: true })).toBe(true);
    expect(document.activeElement).toBe(input);

    // Tab on the last tabbable element wraps to the first one.
    close.focus();
    expect(fireEvent.keyDown(close, { key: "Tab", cancelable: true })).toBe(false);
    expect(document.activeElement).toBe(input);

    // Shift+Tab on the first tabbable element wraps to the last one.
    expect(fireEvent.keyDown(input, { key: "Tab", shiftKey: true, cancelable: true })).toBe(false);
    expect(document.activeElement).toBe(close);
  });
});
