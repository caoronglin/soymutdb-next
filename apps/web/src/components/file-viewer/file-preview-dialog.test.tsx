// @vitest-environment jsdom
import * as React from "react";
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { stableT } from "@/test/mocks";

import { FilePreviewDialog } from "./file-preview-dialog";
import type { RemotePreviewConfig } from "./preview-policy";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: stableT }),
}));

vi.mock("@/lib/antd", () => ({
  Modal: ({
    open,
    children,
    title,
  }: {
    open?: boolean;
    children?: React.ReactNode;
    title?: React.ReactNode;
  }) =>
    open ? (
      <div role="dialog">
        <div>{title}</div>
        {children}
      </div>
    ) : null,
  Button: ({
    children,
    icon,
    type: _type,
    size: _size,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { icon?: React.ReactNode }) => (
    <button {...props}>
      {icon}
      {children}
    </button>
  ),
  Dropdown: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
  Skeleton: () => <div data-testid="skeleton" />,
  Tag: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
  Tooltip: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
}));

const CONFIG: RemotePreviewConfig = {
  siteVariant: "external",
  viewerUrl: "https://viewer.example.net/?file={url}",
  artifactOrigins: ["https://files.example.org"],
};

const SIGNED =
  "https://files.example.org/releases/v1/sample.png?expires=600&X-Amz-Signature=abc";

function renderDialog(files: Parameters<typeof FilePreviewDialog>[0]["files"]) {
  return render(
    <FilePreviewDialog
      files={files}
      open
      remotePreview={CONFIG}
      onOpenChange={() => {}}
    />,
  );
}

afterEach(cleanup);

describe("FilePreviewDialog remote preview", () => {
  it("embeds the configured viewer for a public, signed, release-bound file", () => {
    renderDialog([
      {
        name: "sample.png",
        url: SIGNED,
        size: 1024,
        visibility: "public",
      },
    ]);

    const frame = screen.getByTestId("file-preview-remote");
    expect(frame.getAttribute("src")).toContain("https://viewer.example.net/?file=");
    expect(frame.getAttribute("src")).toContain(encodeURIComponent(SIGNED));
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts allow-same-origin allow-popups");
    expect(frame.getAttribute("referrerpolicy")).toBe("no-referrer");
    expect(screen.queryByAltText("sample.png")).toBeNull();
  });

  it("keeps a file whose visibility was not declared in the local viewer", () => {
    renderDialog([{ name: "sample.png", url: SIGNED, size: 1024 }]);

    expect(screen.queryByTestId("file-preview-remote")).toBeNull();
    expect(screen.getByAltText("sample.png").getAttribute("src")).toBe(SIGNED);
  });

  it("keeps an unsigned catalogue location local even when the variant is configured", () => {
    renderDialog([
      {
        name: "sample.png",
        url: "https://files.example.org/releases/v1/sample.png",
        size: 1024,
        visibility: "public",
      },
    ]);

    expect(screen.queryByTestId("file-preview-remote")).toBeNull();
    expect(screen.getByAltText("sample.png").getAttribute("src")).toBe(
      "https://files.example.org/releases/v1/sample.png",
    );
  });

  it("degrades on a deadline when the provider never answers", () => {
    vi.useFakeTimers();
    try {
      renderDialog([
        { name: "sample.png", url: SIGNED, size: 1024, visibility: "public" },
      ]);
      expect(screen.getByTestId("file-preview-remote")).toBeTruthy();
      expect(screen.queryByTestId("file-preview-remote-fallback")).toBeNull();

      act(() => {
        vi.advanceTimersByTime(8000);
      });

      // The unavailable provider leaves a visible note and the same artifact
      // renders in the built-in viewer instead of a blank frame.
      expect(screen.queryByTestId("file-preview-remote")).toBeNull();
      expect(screen.getByTestId("file-preview-remote-fallback").textContent).toBe(
        "The external preview service is unavailable — showing the built-in viewer instead.",
      );
      expect(screen.getByAltText("sample.png").getAttribute("src")).toBe(SIGNED);
    } finally {
      vi.useRealTimers();
    }
  });
});