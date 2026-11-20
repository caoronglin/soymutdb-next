/**
 * The single copy affordance.
 *
 * The behaviours that matter are the ones the three ad-hoc versions disagreed
 * on: what happens when the clipboard is missing, what happens when it refuses,
 * and whether the reader is told either way.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/lib/antd", () => ({
  Button: ({ children, icon, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    icon?: React.ReactNode;
  }) => (
    <button {...props}>
      {icon}
      {children}
    </button>
  ),
  Tooltip: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

import { CopyValue } from "./copy-value";

const originalClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");

function setClipboard(value: unknown) {
  Object.defineProperty(navigator, "clipboard", {
    value,
    configurable: true,
    writable: true,
  });
}

beforeEach(() => {
  setClipboard({ writeText: vi.fn().mockResolvedValue(undefined) });
});

afterEach(() => {
  if (originalClipboard) {
    Object.defineProperty(navigator, "clipboard", originalClipboard);
  } else {
    setClipboard(undefined);
  }
  vi.restoreAllMocks();
});

describe("CopyValue", () => {
  it("writes the exact value and confirms it", async () => {
    render(<CopyValue value="Glyma.01G000100" testId="copy-gene" />);

    fireEvent.click(screen.getByTestId("copy-gene"));

    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith("Glyma.01G000100"),
    );
    await waitFor(() => expect(screen.getByTestId("copy-gene").dataset.copyState).toBe("copied"));
  });

  it("reports a refused clipboard instead of looking successful", async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("denied")) });
    render(<CopyValue value="x" testId="copy-gene" />);

    fireEvent.click(screen.getByTestId("copy-gene"));

    await waitFor(() => expect(screen.getByTestId("copy-gene").dataset.copyState).toBe("failed"));
  });

  it("fails closed when the clipboard API is unavailable", async () => {
    // An insecure origin has no `navigator.clipboard` at all.
    setClipboard(undefined);
    render(<CopyValue value="x" testId="copy-gene" />);

    fireEvent.click(screen.getByTestId("copy-gene"));

    await waitFor(() => expect(screen.getByTestId("copy-gene").dataset.copyState).toBe("failed"));
  });

  it("announces the outcome for assistive technology", async () => {
    render(<CopyValue value="x" testId="copy-gene" />);

    fireEvent.click(screen.getByTestId("copy-gene"));

    // A colour change alone is silent; the status region carries the words,
    // and it names the value so several copy buttons stay distinguishable.
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("common.copied x"),
    );
  });
});
