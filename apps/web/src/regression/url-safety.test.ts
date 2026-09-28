// @vitest-environment jsdom
//
// REGRESSION — server-supplied URLs are scheme-checked before they become a
// navigation target.
//
// Invariant: only absolute `http:`/`https:` URLs may reach an `href` or
// `window.open`. A stored file location, a federated hit, or a CMS link can
// carry `javascript:`, `data:`, `file:` or a relative value; rendering any of
// those verbatim turns a data field into script execution or an exfiltration
// channel.
//
// If this is RED: a public surface is forwarding an unvalidated URL to the
// browser, and a poisoned data row becomes client-side code execution.
import { describe, expect, it } from "vitest";

import { isSafeExternalUrl, safeExternalUrl } from "../lib/url-safety";

describe("safeExternalUrl", () => {
  it("accepts absolute http and https targets", () => {
    expect(safeExternalUrl("https://files.example/x.vcf.gz")).toBe(
      "https://files.example/x.vcf.gz",
    );
    expect(safeExternalUrl("http://localhost:9000/x")).toBe("http://localhost:9000/x");
  });

  it("rejects script, data, file and other non-navigable schemes", () => {
    for (const hostile of [
      "javascript:alert(1)",
      "JavaScript:alert(1)",
      "data:text/html,<script>alert(1)</script>",
      "data:image/svg+xml,<svg onload=alert(1)>",
      "file:///etc/passwd",
      "ftp://files.example/x",
      "blob:https://evil.example/abc",
      "mailto:research@example.com",
    ]) {
      expect(safeExternalUrl(hostile), hostile).toBeUndefined();
      expect(isSafeExternalUrl(hostile), hostile).toBe(false);
    }
  });

  it("rejects relative and malformed values", () => {
    for (const value of ["/downloads/x", "x.vcf.gz", "", "   ", "not a url", "//evil.example/x"]) {
      expect(safeExternalUrl(value), value).toBeUndefined();
    }
    expect(safeExternalUrl(undefined)).toBeUndefined();
    expect(safeExternalUrl(null)).toBeUndefined();
  });

  it("preserves the query string of a signed URL", () => {
    const signed = "https://s3.example/bucket/key?X-Amz-Signature=abc&X-Amz-Expires=3600";
    expect(safeExternalUrl(signed)).toBe(signed);
  });

  it("normalises an accepted URL rather than returning the raw input", () => {
    // `new URL` resolves default ports and trailing whitespace, so the value
    // handed to the browser is the parsed one.
    expect(safeExternalUrl("  https://files.example/x  ")).toBe("https://files.example/x");
  });
});
