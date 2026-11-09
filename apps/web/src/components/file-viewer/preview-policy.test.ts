import { describe, expect, it } from "vitest";

import {
  resolvePreviewRoute,
  type PreviewRouteInput,
  type RemotePreviewConfig,
} from "./preview-policy";

const CONFIG: RemotePreviewConfig = {
  siteVariant: "external",
  viewerUrl: "https://viewer.example.net/?file={url}",
  artifactOrigins: ["https://files.example.org"],
};

const SIGNED = "https://files.example.org/releases/v1/genome.fa?X-Amz-Expires=600&X-Amz-Signature=abc";

function route(overrides: Partial<PreviewRouteInput> = {}) {
  return resolvePreviewRoute({
    siteVariant: "external",
    visibility: "public",
    config: CONFIG,
    url: SIGNED,
    ...overrides,
  });
}

describe("resolvePreviewRoute", () => {
  it("routes a public released artifact with a signed URL to the configured viewer", () => {
    const result = route();
    expect(result.mode).toBe("remote");
    if (result.mode !== "remote") throw new Error("expected remote");
    expect(result.url.startsWith("https://viewer.example.net/?file=")).toBe(true);
    expect(result.url).toContain(encodeURIComponent(SIGNED));
  });

  it("keeps an artifact whose visibility was not proven public in the local viewer", () => {
    expect(route({ visibility: "internal" })).toEqual({ mode: "local" });
  });

  it("never uses a provider configured for the other site variant", () => {
    expect(route({ siteVariant: "internal" })).toEqual({ mode: "local" });
  });

  it("requires a signed URL with a positive lifetime", () => {
    expect(route({ url: "https://files.example.org/releases/v1/genome.fa" })).toEqual({
      mode: "local",
    });
    expect(route({ url: `${SIGNED.split("?")[0]}?expires=0` })).toEqual({ mode: "local" });
    expect(route({ url: `${SIGNED.split("?")[0]}?expires=soon` })).toEqual({ mode: "local" });
  });

  it("rejects plaintext and credential-bearing artifact locations", () => {
    expect(
      route({ url: "http://files.example.org/releases/v1/genome.fa?expires=600" }),
    ).toEqual({ mode: "local" });
    expect(route({ url: "https://user:pass@files.example.org/a.fa?expires=600" })).toEqual({
      mode: "local",
    });
  });

  it("rejects an artifact origin that the variant configuration does not allow", () => {
    expect(route({ url: "https://cdn.elsewhere.net/a.fa?expires=600" })).toEqual({
      mode: "local",
    });
  });

  it("rejects a viewer that is not an https location", () => {
    expect(route({ config: { ...CONFIG, viewerUrl: "http://viewer.example.net/" } })).toEqual({
      mode: "local",
    });
  });

  it("stays local when the provider is not configured", () => {
    expect(route({ config: undefined })).toEqual({ mode: "local" });
  });

  it("appends the encoded location when the viewer URL has no placeholder", () => {
    const result = route({ config: { ...CONFIG, viewerUrl: "https://viewer.example.net/view" } });
    expect(result).toEqual({
      mode: "remote",
      url: `https://viewer.example.net/view?url=${encodeURIComponent(SIGNED)}`,
    });
  });
});