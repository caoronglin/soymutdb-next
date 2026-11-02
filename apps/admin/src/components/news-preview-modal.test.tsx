import * as React from "react";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { getPreviewToken } from "@soymutdb/api-client";

vi.mock("@soymutdb/api-client", () => ({ getPreviewToken: vi.fn() }));
vi.mock("react-i18next", () => {
  // These boundary tests assert keys; keep their translator stable across renders.
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("../lib/antd", async () => {
  const doubles = await import("../test/antd-double");
  return {
    ...doubles,
    Button: (props: Record<string, unknown>) => props.href
      ? <a href={String(props.href)} target={String(props.target)} rel={String(props.rel)}>{props.children as React.ReactNode}</a>
      : <doubles.Button {...props} />,
  };
});
import { NewsPreviewModal } from "./news-preview-modal";

const props = { open: true, article: { id: 1, slug: "draft-news" }, onClose: vi.fn() };
const copyLabel = "admin.news.preview.copyLink";
const openLabel = "admin.news.preview.openPreview";
beforeEach(() => {
  vi.clearAllMocks();
  vi.stubEnv("VITE_PUBLIC_URL", "https://portal.soymutdb.org");
  vi.mocked(getPreviewToken).mockResolvedValue({ preview: "token+&?", exp: 2000000000, url: "/api/v1/news/ignored?preview=do-not-use" });
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: vi.fn().mockResolvedValue(undefined) } });
});
afterEach(() => { cleanup(); vi.unstubAllEnvs(); });

describe("news preview portal boundary", () => {
  it.each([undefined, "", "  ", "/admin/", "//portal.soymutdb.org", "https://www.example.com", "http://portal.soymutdb.org", "javascript://localhost/test"])("fails closed for unconfigured or invalid origin %s", (origin) => {
    vi.stubEnv("VITE_PUBLIC_URL", origin);
    render(<NewsPreviewModal {...props} />);
    const warning = screen.getAllByRole("alert")[1];
    expect(warning).toHaveTextContent("admin.news.preview.originMissing");
    expect(warning).toHaveTextContent("admin.news.preview.originMissingHint");
    expect(screen.getByRole("button", { name: copyLabel })).toBeDisabled();
    expect(screen.getByRole("button", { name: openLabel })).toBeDisabled();
    expect(screen.queryByRole("link")).toBeNull();
    expect(getPreviewToken).not.toHaveBeenCalled();
  });
  it("uses the configured portal HTML route, not the admin origin or API response URL", async () => {
    vi.stubEnv("VITE_PUBLIC_URL", " https://portal.soymutdb.org/ ");
    render(<NewsPreviewModal {...props} article={{ id: 1, slug: "a/b ?中" }} />);
    const link = await screen.findByRole("link", { name: openLabel });
    const url = new URL(link.getAttribute("href")!);
    expect(url.origin).toBe("https://portal.soymutdb.org");
    expect(url.pathname).toBe("/news/a%2Fb%20%3F%E4%B8%AD");
    expect(url.searchParams.get("preview")).toBe("token+&?");
    expect(url.searchParams.get("exp")).toBe("2000000000");
    expect(url.pathname).not.toContain("api/v1");
    fireEvent.click(screen.getByRole("button", { name: copyLabel }));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(url.href));
    expect(link.getAttribute("rel")).toBe("noreferrer");
  });
  it.each(["https://pages.soymutdb.org/project/", "https://pages.soymutdb.org/project"])("preserves an explicit portal base path: %s", async (base) => {
    vi.stubEnv("VITE_PUBLIC_URL", base);
    render(<NewsPreviewModal {...props} />);
    const link = await screen.findByRole("link", { name: openLabel });
    expect(new URL(link.getAttribute("href")!).pathname).toBe("/project/news/draft-news");
  });
  it("clears pending loading state when the article is removed", () => {
    vi.mocked(getPreviewToken).mockReturnValue(new Promise(() => {}));
    const view = render(<NewsPreviewModal {...props} />);
    expect(screen.getByText("admin.news.preview.loading")).toBeTruthy();
    view.rerender(<NewsPreviewModal {...props} article={null} />);
    expect(screen.queryByText("admin.news.preview.loading")).toBeNull();
    expect(screen.getByRole("button", { name: copyLabel })).toBeDisabled();
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("allows an explicitly configured local HTTP portal", async () => {
    vi.stubEnv("VITE_PUBLIC_URL", "http://localhost:8090");
    render(<NewsPreviewModal {...props} />);
    const link = await screen.findByRole("link", { name: openLabel });
    expect(link.getAttribute("href")).toContain("http://localhost:8090/news/draft-news?");
  });
  it("keeps actions disabled while loading and renders request failure", async () => {
    vi.mocked(getPreviewToken).mockRejectedValue(new Error("preview unavailable"));
    render(<NewsPreviewModal {...props} />);
    expect(screen.getByRole("button", { name: copyLabel })).toBeDisabled();
    expect(await screen.findByText("preview unavailable")).toBeTruthy();
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("never attaches a previous or late token to another article", async () => {
    let resolveOld!: (value: Awaited<ReturnType<typeof getPreviewToken>>) => void;
    vi.mocked(getPreviewToken).mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    const view = render(<NewsPreviewModal {...props} />);
    view.rerender(<NewsPreviewModal {...props} article={{ id: 2, slug: "second" }} />);
    const link = await screen.findByRole("link", { name: openLabel });
    expect(link.getAttribute("href")).toContain("/news/second?");
    await act(async () => resolveOld({ preview: "old-secret", exp: 1, url: "/api/v1/news/draft-news" }));
    expect(screen.getByRole("link", { name: openLabel }).getAttribute("href")).not.toContain("old-secret");
    view.rerender(<NewsPreviewModal {...props} open={false} />);
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("does not remint tokens when the parent recreates equivalent article props", async () => {
    const view = render(<NewsPreviewModal {...props} />);
    await screen.findByRole("link", { name: openLabel });
    view.rerender(<NewsPreviewModal {...props} article={{ ...props.article }} />);
    expect(getPreviewToken).toHaveBeenCalledTimes(1);
  });
  it("keeps deployment configuration explicit instead of using the admin base", () => {
    const config = readFileSync("config/config.ts", "utf8");
    expect(config).toContain('VITE_PUBLIC_URL: env.VITE_PUBLIC_URL?.trim() || ""');
    expect(config).not.toContain("VITE_PUBLIC_URL: env.VITE_PUBLIC_URL || base");
  });
});
