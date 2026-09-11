import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const searchGenesMock = vi.hoisted(() => vi.fn());
vi.mock("@soymutdb/api-client", () => ({ searchGenes: searchGenesMock }));

import { AdminCommandPalette } from "./admin-command-palette";

const input = () => screen.getByRole("combobox", { name: "Search commands and genes" });

describe("AdminCommandPalette", () => {
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
    vi.useFakeTimers();
    searchGenesMock.mockResolvedValueOnce({ items: [{ id: "1", gene_id: "Glyma.01G000100", symbol: "ABC", name: null }] });
    const onOpenGene = vi.fn();
    render(<AdminCommandPalette onClose={vi.fn()} onNavigate={vi.fn()} onOpenGene={onOpenGene} open />);
    fireEvent.change(input(), { target: { value: "Gly" } });
    expect(searchGenesMock).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(250); await Promise.resolve(); });
    expect(searchGenesMock).toHaveBeenCalledWith({ q: "Gly", limit: 5 });
    const result = await screen.findByRole("option", { name: /Glyma.01G000100/i });
    fireEvent.click(result);
    expect(onOpenGene).toHaveBeenCalledWith("Glyma.01G000100");
  });

  it("never performs a user lookup; suggestions use only the bounded gene catalogue", async () => {
    vi.useFakeTimers();
    render(<AdminCommandPalette onClose={vi.fn()} onNavigate={vi.fn()} onOpenGene={vi.fn()} open />);

    fireEvent.change(input(), { target: { value: "operator@example.test" } });
    await act(async () => { vi.advanceTimersByTime(250); await Promise.resolve(); });

    expect(searchGenesMock).toHaveBeenCalledWith({ q: "operator@example.test", limit: 5 });
    expect(screen.queryByText(/user/i)).not.toBeInTheDocument();
  });

  it("supports keyboard navigation and escape", () => {
    const onClose = vi.fn();
    const onNavigate = vi.fn();
    render(<AdminCommandPalette onClose={onClose} onNavigate={onNavigate} onOpenGene={vi.fn()} open />);
    fireEvent.keyDown(input(), { key: "ArrowDown" });
    fireEvent.keyDown(input(), { key: "Enter" });
    expect(onNavigate).toHaveBeenCalledWith("/imports");
    fireEvent.keyDown(input(), { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });
});
