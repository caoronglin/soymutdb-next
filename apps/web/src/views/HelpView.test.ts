// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";

import { getSiteContent } from "@soymutdb/api-client";
import { mountPortalView } from "../test/mount-portal-view";
import { setLanguage, t } from "../lib/i18n";
import { beforeEach, describe, expect, it, vi } from "vitest";
import HelpView from "./HelpView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getSiteContent: vi.fn() };
});

const mockedSiteContent = vi.mocked(getSiteContent);

beforeEach(() => {
  setLanguage("en");
  mockedSiteContent.mockReset().mockResolvedValue({});
});

async function mountHelp() {
  const result = mountPortalView(HelpView, { path: "/help" });
  await flushPromises();
  await flushPromises();
  return result;
}

describe("HelpView FAQ catalog mapping", () => {
  it("renders all six questions from the help.q{i} catalog keys", async () => {
    const { wrapper } = await mountHelp();

    const questions = wrapper.findAll('[data-testid^="help-question-"]');
    expect(questions).toHaveLength(6);
    for (let index = 0; index < 6; index += 1) {
      // The catalog name is help.q{i}; the backend key is help.faq{i}.q.
      expect(questions[index].text()).toBe(t(`help.q${index + 1}.q`));
    }
    wrapper.unmount();
  });
});

describe("HelpView editable content", () => {
  it("renders operator overrides for FAQ 1 and the contact heading", async () => {
    mockedSiteContent.mockResolvedValue({
      "help.faq1.q": "运营问题",
      "help.contact": "运营支持",
      "help.faq": "运营常见问题",
      "help.gettingStarted": "运营快速开始",
    });

    const { wrapper } = await mountHelp();

    expect(wrapper.get('[data-testid="help-question-0"]').text()).toBe("运营问题");
    expect(wrapper.get("#help-contact").text()).toBe("运营支持");
    expect(wrapper.get("#help-faq").text()).toBe("运营常见问题");
    expect(wrapper.get("#help-getting-started").text()).toBe("运营快速开始");
    // Entries without a stored override keep their catalog fallback.
    expect(wrapper.get('[data-testid="help-question-1"]').text()).toBe(t("help.q2.q"));
    wrapper.unmount();
  });

  it("renders the operator override for the documentation heading", async () => {
    mockedSiteContent.mockResolvedValue({ "help.documentation": "运营文档" });

    const { wrapper } = await mountHelp();

    expect(wrapper.get("#help-documentation").text()).toBe("运营文档");
    wrapper.unmount();
  });
});
