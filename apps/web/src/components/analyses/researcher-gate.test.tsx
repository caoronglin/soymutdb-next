// @vitest-environment jsdom
/**
 * The researcher gate is the analyses module's permission surface, so its copy
 * is the first thing a non-researcher visitor reads.
 *
 * `check_visible_i18n_react` only proves the page carries no hardcoded string;
 * it cannot prove the page actually *uses* the catalog. These renders drive
 * the real component with a `t` backed by the shipped catalog, so a component
 * that kept its own literal — or looked up a key that does not exist — shows
 * up here as English text in the zh render or as a raw dotted key.
 */
import * as React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createInstance } from "i18next";

import { buildBaseI18nOptions } from "@soymutdb/i18n-core";

const state = vi.hoisted(() => ({ isResearcher: false, isLoading: false }));

vi.mock("../../lib/use-current-user", () => ({
  useIsResearcher: () => ({ isResearcher: state.isResearcher, isLoading: state.isLoading }),
}));

const i18n = createInstance();
i18n.init({ ...buildBaseI18nOptions("en"), lng: "en", initImmediate: false });
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: i18n.t, i18n }),
}));

import { ResearcherGate } from "../../components/analyses/researcher-gate";

afterEach(() => {
  // Without this the previous render stays mounted and `document.body`
  // accumulates every assertion's copy, which makes the last test's
  // "not.toContain" depend on run order.
  cleanup();
  vi.restoreAllMocks();
});

function renderGate() {
  return render(<ResearcherGate><p>gate-open</p></ResearcherGate>);
}

describe("ResearcherGate copy", () => {
  it("renders the catalog copy for a denied visitor, not an inline literal", () => {
    state.isResearcher = false;
    state.isLoading = false;
    renderGate();
    expect(screen.getByText(i18n.t("analyses.gate.title"))).toBeTruthy();
    expect(screen.getByText(i18n.t("analyses.gate.description"))).toBeTruthy();
    expect(screen.getByRole("button", { name: new RegExp(i18n.t("analyses.gate.signIn"), "i") })).toBeTruthy();
    // No raw key may reach the page.
    expect(document.body.textContent).not.toContain("analyses.gate.");
  });

  it("translates the same gate when the reader switches to zh", async () => {
    state.isResearcher = false;
    state.isLoading = false;
    await i18n.changeLanguage("zh");
    renderGate();
    expect(screen.getByText("需要研究权限")).toBeTruthy();
    expect(screen.getByText(/仅对研究者及以上账户开放/)).toBeTruthy();
    expect(document.body.textContent).not.toContain("analyses.gate.");
    await i18n.changeLanguage("en");
  });

  it("renders children once the capability check passes", () => {
    state.isResearcher = true;
    state.isLoading = false;
    renderGate();
    expect(screen.getByText("gate-open")).toBeTruthy();
    expect(document.body.textContent).not.toContain("Research access required");
  });
});