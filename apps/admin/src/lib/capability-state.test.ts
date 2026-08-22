import { describe, expect, it } from "vitest";
import { resolveFeatureState, resolvePluginState } from "./capability-state";

describe("capability UI state", () => {
  it("does not collapse loading, request failure, unknown and disabled features", () => {
    expect(resolveFeatureState({ pending: true }, "imports.module_tsv")).toBe("loading");
    expect(resolveFeatureState({ error: true }, "imports.module_tsv")).toBe("error");
    expect(resolveFeatureState({ features: {} }, "imports.module_tsv")).toBe("unknown");
    expect(
      resolveFeatureState(
        { features: { "imports.module_tsv": false } },
        "imports.module_tsv",
      ),
    ).toBe("disabled");
    expect(
      resolveFeatureState(
        { features: { "imports.module_tsv": true } },
        "imports.module_tsv",
      ),
    ).toBe("enabled");
  });

  it("preserves plugin unavailability reasons after the snapshot loads", () => {
    expect(resolvePluginState({ pending: true }, "jbrowse")).toEqual({
      state: "loading",
      reason: null,
    });
    expect(resolvePluginState({ error: true }, "jbrowse")).toEqual({
      state: "error",
      reason: null,
    });
    expect(resolvePluginState({ plugins: {} }, "jbrowse")).toEqual({
      state: "unavailable",
      reason: "not_installed",
    });
    expect(
      resolvePluginState(
        {
          plugins: {
            jbrowse: {
              installed: true,
              enabled: false,
              configured: true,
              healthy: true,
              reason: null,
            },
          },
        },
        "jbrowse",
      ),
    ).toEqual({ state: "unavailable", reason: "plugin_disabled" });
  });
});
