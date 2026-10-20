import * as React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const { ConfirmDialog } = await import("./confirm-dialog");

function props() {
  return { open: true, title: "Confirm operation", description: "Changes public data", onOpenChange: vi.fn(), onConfirm: vi.fn() };
}

describe("confirmation safeguards", () => {
  it("requires the exact phrase before dispatching and resets it on reopen", () => {
    const callbacks = props();
    const view = render(<ConfirmDialog {...callbacks} confirmPhrase="PUBLISH" />);
    const confirm = screen.getByRole("button", { name: "Confirm" });
    expect(confirm).toBeDisabled();
    fireEvent.click(confirm);
    expect(callbacks.onConfirm).not.toHaveBeenCalled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "publish" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "PUBLISH" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(callbacks.onConfirm).toHaveBeenCalledTimes(1);
    view.rerender(<ConfirmDialog {...callbacks} open={false} confirmPhrase="PUBLISH" />);
    view.rerender(<ConfirmDialog {...callbacks} confirmPhrase="PUBLISH" />);
    expect(screen.getByRole("button", { name: "Confirm" })).toBeDisabled();
  });

  it("cannot dismiss or dispatch while pending even when the phrase is entered", () => {
    const callbacks = props();
    render(<ConfirmDialog {...callbacks} loading confirmPhrase="PUBLISH" error="Previous refusal" />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "PUBLISH" } });
    expect(screen.getByRole("button", { name: "Working…" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Working…" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(callbacks.onConfirm).not.toHaveBeenCalled();
    expect(callbacks.onOpenChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Previous refusal");
  });
});
