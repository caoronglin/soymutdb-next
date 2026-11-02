/**
 * The analyses module's catalog entries must resolve through the real i18next
 * instance, not merely exist in the JSON.
 *
 * A key that is present but unreachable renders as its own dotted path on the
 * page. The plural keys added for the upload dropzone are the sharpest case:
 * `t(key, { count })` resolves `key_one` / `key_other`, so an entry written
 * without the suffix (or with the wrong one) silently falls back to the raw
 * key. This file builds an i18next instance from the shipped catalogs and
 * resolves the keys the components actually call.
 */
import { describe, expect, it } from "vitest";
import { createInstance } from "i18next";

import { buildBaseI18nOptions } from "@soymutdb/i18n-core";

function instance(language: "en" | "zh") {
  const i18n = createInstance();
  i18n.init({ ...buildBaseI18nOptions(language), lng: language, initImmediate: false });
  return i18n;
}

describe("analyses catalog entries resolve", () => {
  it.each(["en", "zh"] as const)("resolves both upload shapes in %s", (language) => {
    const t = instance(language).t;
    const values = { format: "FASTQ", extensions: ".fastq", maxSize: "500 MB", maxFiles: 2 };
    for (const key of [
      "analyses.upload.ariaLabelSingle",
      "analyses.upload.ariaLabelMulti",
      "analyses.upload.dropHereSingle",
      "analyses.upload.dropHereMulti",
      "analyses.upload.browseHintSingle",
      "analyses.upload.browseHintMulti",
    ]) {
      const rendered = t(key, values);
      expect(rendered).not.toBe(key);
      expect(rendered).not.toContain("{{");
    }
  });

  it("keeps the interpolated job summary whole in both languages", () => {
    for (const language of ["en", "zh"] as const) {
      const t = instance(language).t;
      const rendered = t("analyses.job.summary", { id: "abc12345", submitted: "2026-10-02" });
      expect(rendered).toContain("abc12345");
      expect(rendered).toContain("2026-10-02");
      expect(rendered).not.toContain("{{");
    }
  });

  it("resolves the researcher gate copy the gate component asks for", () => {
    for (const language of ["en", "zh"] as const) {
      const t = instance(language).t;
      for (const key of [
        "analyses.gate.checking",
        "analyses.gate.title",
        "analyses.gate.description",
        "analyses.gate.signIn",
        "analyses.gate.backHome",
      ]) {
        expect(t(key)).not.toBe(key);
      }
    }
  });
});