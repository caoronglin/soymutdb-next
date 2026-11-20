// @vitest-environment jsdom
import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/site-content-react", () => ({
    useSiteContent: () => ({ get: (_key: string, fallback?: string) => fallback ?? "" }),
}));

import { Markdown } from "./guide";

const PUBLISHED_PAGE = {
    id: "page-malicious",
    slug: "ncbi-database-guide",
    title_en: "NCBI Database Guide",
    title_zh: null,
    content_en: [
        "[HTTP](http://example.com/docs) [HTTPS](https://example.com/docs) [root](/guide#retrieval) [hash](#retrieval) [relative](./appendix)",
        "[JavaScript](javascript:alert(1)) [Data](data:text/html,%3Csvg%20onload%3Dalert%281%29%3E) [VBScript](vbscript:msgbox(1)) [FTP](ftp://example.com/file) [Mail](mailto:research@example.com) [Protocol relative](//evil.example/collect) [Backslash relative](\\\\evil.example/collect)",
    ].join("\n\n"),
    content_zh: null,
    status: "published",
    category: "documentation",
    summary: null,
    sort_order: 0,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
} as const;

afterEach(() => {
    cleanup();
});

describe("published guide Markdown links", () => {
    it("renders only HTTP(S) and same-origin relative/hash targets as links", () => {
        render(<Markdown content={PUBLISHED_PAGE.content_en} />);

        const safeLinks = [
            ["HTTP", "http://example.com/docs"],
            ["HTTPS", "https://example.com/docs"],
            ["root", "/guide#retrieval"],
            ["hash", "#retrieval"],
            ["relative", "./appendix"],
        ] as const;
        for (const [label, href] of safeLinks) {
            expect(screen.getByRole("link", { name: label }).getAttribute("href")).toBe(href);
        }

        for (const label of [
            "JavaScript",
            "Data",
            "VBScript",
            "FTP",
            "Mail",
            "Protocol relative",
            "Backslash relative",
        ]) {
            expect(screen.queryByRole("link", { name: label })).toBeNull();
        }

        // Rejected targets remain readable, but are not actionable anchors.
        expect(screen.getByText(/JavaScript/)).toBeTruthy();
        expect(screen.getByText(/Protocol relative/)).toBeTruthy();
    });

    it("escapes raw HTML and stamps heading anchors for the table of contents", () => {
        const { container } = render(
            <Markdown
                content={[
                    "## Retrieval",
                    "",
                    "<script>alert(1)</script>",
                    "",
                    "### Sub Section",
                ].join("\n")}
            />,
        );

        expect(screen.getByRole("heading", { name: "Retrieval" }).id).toBe("retrieval");
        expect(screen.getByRole("heading", { name: "Sub Section" }).id).toBe("sub-section");

        // Raw HTML is shown as text, never executed as markup.
        expect(screen.getByText(/alert\(1\)/)).toBeTruthy();
        expect(container.querySelector("script")).toBeNull();
    });
});
