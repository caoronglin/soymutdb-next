import { describe, expect, it } from "vitest";
import i18next from "i18next";

import { buildBaseI18nOptions } from "@soymutdb/i18n-core";

/**
 * Interpolation contract for the shared catalogs.
 *
 * i18next substitutes its own `{{var}}` syntax. The catalog previously mixed
 * `{count}` and `{{count}}`, so counts rendered literally as "{count} results".
 * This test pins the working syntax in both languages; the catalog-wide syntax
 * sweep lives in @soymutdb/i18n-core.
 */
describe("portal i18n interpolation", () => {
  it("substitutes placeholders in both languages", async () => {
    const instance = i18next.createInstance();
    await instance.init(buildBaseI18nOptions("en"));

    expect(instance.t("variants.totalCount", { count: 7, lng: "en" })).toBe("7 results");
    expect(instance.t("variants.totalCount", { count: 7, lng: "zh" })).toBe("共 7 条");
    expect(instance.t("search.location.found", { count: 3, lng: "en" })).toBe(
      "3 mutation sites found",
    );
    expect(instance.t("variants.pageOf", { page: 2, lng: "en" })).toBe("Page 2");
  });
});
