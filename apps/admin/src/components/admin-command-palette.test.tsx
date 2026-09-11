import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const searchGenesMock = vi.hoisted(() => vi.fn());
vi.mock("@soymutdb/api-client", () => ({ searchGenes: searchGenesMock }));

import { AdminCommandPalette } from "./admin-command-palette";

const input = () => screen.getByRole("combobox", { name: "Search commands and genes" });

describe("AdminCommandPalette", () => {
  beforeEach(() => {
    // Default the bounded gene lookup to an empty result. Without this the mock
    // returns `undefined`, and the component's `searchGenes(...).then(...)`
    // throws instead of exercising the debounce.
    searchGenesMock.mockReset();
    searchGenesMock.mockResolvedValue({ items: [] });
  });

  afterEach(() => { vi.useRealTimers(); });

  it("filters commands and executes the active result", () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();
    render(<AdminCommandPalette onClose={onClose} onNavigate={onNavigate} onOpenGene={vi.fn()} open />);
    fireEvent.change(input(), { target: { value: "settings" } });
    expect(screen.getByRole("option", { name: /open settings/i })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /start a data import/i })).not.toBeInTheDocument();
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("/settings");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("debounces bounded gene lookups and opens selected public gene", async () => {
    searchGenesMock.mockResolvedValueOnce({ items: [{ id: "1", gene_id: "Glyma.01G000100", symbol: "ABC", name: null }] });
    const onOpenGene = vi.fn();
    render(<AdminCommandPalette onClose={vi.fn()} onNavigate={vi.fn()} onOpenGene={onOpenGene} open />);
    fireEvent.change(input(), { target: { value: "Gly" } });
    // The debounce window has not elapsed yet, so no lookup has been issued.
    expect(searchGenesMock).not.toHaveBeenCalled();

    // `findByRole` polls on real timers, so let the debounce elapse on real
    // time rather than mixing fake timers with async queries.
    await waitFor(() => expect(searchGenesMock).toHaveBeenCalledWith({ q: "Gly", limit: 5 }));
    const result = await screen.findByRole("option", { name: /Glyma.01G000100/i });
    fireEvent.click(result);
    expect(onOpenGene).toHaveBeenCalledWith("Glyma.01G000100");
  });

  it("never performs a user lookup; suggestions use only the bounded gene catalogue", async () => {
    render(<AdminCommandPalette onClose={vi.fn()} onNavigate={vi.fn()} onOpenGene={vi.fn()} open />);

    fireEvent.change(input(), { target: { value: "operator@example.test" } });
    await waitFor(() =>
      expect(searchGenesMock).toHaveBeenCalledWith({ q: "operator@example.test", limit: 5 }),
    );

    // Only the bounded gene query runs; no user/account lookup endpoint exists.
    expect(searchGenesMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/user/i)).not.toBeInTheDocument();
  });

  it("supports keyboard navigation and escape", () => {
    // ArrowDown moves the active option, then Escape must close the palette.
    const onClose = vi.fn();
    render(<AdminCommandPalette onClose={onClose} onNavigate={vi.fn()} onOpenGene={vi.fn()} open />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("runs the active command on Enter", () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();
    render(<AdminCommandPalette onClose={onClose} onNavigate={onNavigate} onOpenGene={vi.fn()} open />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("/imports");
    expect(onClose).toHaveBeenCalledOnce();
  });
});
