/**
 * Media library contract.
 *
 * The purpose filter built its labels from a dynamic i18n key
 * (`admin.media.purposes.<value>`) without a `defaultValue`, and the flattened
 * catalogues had no `admin.media.purposes` node at all. The dropdown therefore
 * showed the literal strings `admin.media.purposes.news` and friends.
 */
import * as React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { en, zh } from "@soymutdb/i18n";

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("@/lib/antd", async () => (await import("../test/antd-double")));

const api = vi.hoisted(() => ({
  listMediaAssets: vi.fn(),
  archiveMediaAsset: vi.fn(),
  updateMediaAsset: vi.fn(),
}));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listMediaAssets: api.listMediaAssets,
    archiveMediaAsset: api.archiveMediaAsset,
    updateMediaAsset: api.updateMediaAsset,
  };
});

// The uploader talks to object storage and the admin upload API; it is not
// what this test is about.
vi.mock("../components/file-upload", () => ({
  default: (props: { buttonText?: string }) => <button type="button">{props.buttonText}</button>,
}));

const MediaPage = (await import("./media")).default;

beforeEach(() => {
  api.listMediaAssets.mockReset().mockResolvedValue({ items: [], total: 0 });
  api.archiveMediaAsset.mockReset().mockResolvedValue({});
  api.updateMediaAsset.mockReset().mockResolvedValue({});
});

describe("media purpose filter", () => {
  it("renders translated purpose labels instead of raw i18n keys", async () => {
    render(<MediaPage />);

    const labels = screen
      .getAllByRole("option")
      .map((option) => option.textContent ?? "");

    expect(labels).toContain("News");
    expect(labels).toContain("Editor");
    expect(labels).toContain("About");
    expect(labels.some((label) => label.includes("admin.media.purposes."))).toBe(false);
    expect(screen.queryByText("admin.media.purposes.news")).toBeNull();
  });

  it("ships a translated purpose label in every locale", () => {
    for (const catalog of [en, zh]) {
      expect(catalog.admin.media.purposes.news).toBeTruthy();
      expect(catalog.admin.media.purposes.editor).toBeTruthy();
      expect(catalog.admin.media.purposes.about).toBeTruthy();
    }
    expect(en.admin.media.purposes.news).not.toBe(zh.admin.media.purposes.news);
  });
});
