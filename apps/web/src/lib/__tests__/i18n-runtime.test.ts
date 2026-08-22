import { describe, expect, it } from "vitest";
import i18n from "@soymutdb/i18n";
import { initI18nOnce } from "../i18n";

describe("portal i18n runtime", () => {
  it("resolves default-namespace keys synchronously after bootstrap", () => {
    initI18nOnce();
    expect(i18n.isInitialized).toBe(true);
    expect(i18n.t("nav.home")).toBe("Home");
    expect(i18n.t("browser.unavailable")).toBe(
      "Genome browser is unavailable for this plugin/assembly.",
    );
  });
});
