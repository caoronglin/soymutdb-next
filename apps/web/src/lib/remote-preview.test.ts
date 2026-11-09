import { describe, expect, it } from "vitest";

import { resolveRemotePreviewConfig } from "./remote-preview";

describe("resolveRemotePreviewConfig", () => {
  it("tags the configured provider with the variant that was built", () => {
    const env = {
      VITE_FILE_VIEWER_URL: "https://viewer.example.net/?file={url}",
      VITE_FILE_VIEWER_ARTIFACT_ORIGINS: "https://files.example.org",
    };

    expect(resolveRemotePreviewConfig("external", env)).toEqual({
      siteVariant: "external",
      viewerUrl: "https://viewer.example.net/?file={url}",
      artifactOrigins: ["https://files.example.org"],
    });
    expect(resolveRemotePreviewConfig("internal", env)?.siteVariant).toBe("internal");
  });

  it("disables remote preview when the viewer or the allowed origins are missing", () => {
    expect(
      resolveRemotePreviewConfig("external", {
        VITE_FILE_VIEWER_ARTIFACT_ORIGINS: "https://files.example.org",
      }),
    ).toBeUndefined();
    expect(
      resolveRemotePreviewConfig("external", {
        VITE_FILE_VIEWER_URL: "https://viewer.example.net/",
        VITE_FILE_VIEWER_ARTIFACT_ORIGINS: " , ",
      }),
    ).toBeUndefined();
  });

  it("parses a comma-separated origin list and trims whitespace", () => {
    const config = resolveRemotePreviewConfig("external", {
      VITE_FILE_VIEWER_URL: " https://viewer.example.net/ ",
      VITE_FILE_VIEWER_ARTIFACT_ORIGINS:
        "https://files.example.org, https://cdn.example.org ",
    });
    expect(config?.viewerUrl).toBe("https://viewer.example.net/");
    expect(config?.artifactOrigins).toEqual([
      "https://files.example.org",
      "https://cdn.example.org",
    ]);
  });
});