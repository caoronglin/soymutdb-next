import { describe, expect, it } from "vitest";
import type { PluginCapability } from "@soymutdb/api-client";
import { resolveEmbeddedPlugin, resolvePluginLauncher } from "../plugin-launcher";

function capability(overrides: Partial<PluginCapability> = {}): PluginCapability {
  return {
    version: "1.0.0",
    installed: true,
    enabled: true,
    configured: true,
    healthy: true,
    public_url: "https://tools.example.test",
    assemblies: ["Glycine max"],
    reason: null,
    ...overrides,
  };
}

describe("plugin launcher resolution", () => {
  it("allows a healthy, assembly-matching HTTPS plugin", () => {
    expect(resolvePluginLauncher(capability(), "Glycine max")).toEqual({
      available: true,
      href: "https://tools.example.test",
      reason: null,
    });
  });

  it.each([
    [undefined, "not_installed"],
    [capability({ installed: false }), "not_installed"],
    [capability({ enabled: false }), "plugin_disabled"],
    [capability({ configured: false }), "not_configured"],
    [capability({ healthy: false, reason: "upstream_timeout" }), "upstream_timeout"],
    [capability({ assemblies: ["Williams 82"] }), "assembly_mismatch"],
    [capability({ public_url: null }), "missing_public_url"],
    [capability({ public_url: "http://tools.example.test" }), "insecure_public_url"],
  ] as const)("fails closed for an unavailable launcher", (plugin, reason) => {
    expect(resolvePluginLauncher(plugin, "Glycine max")).toEqual({
      available: false,
      href: null,
      reason,
    });
  });

  it("allows a healthy embedded OLS4 plugin without a public URL", () => {
    expect(resolveEmbeddedPlugin(capability({ public_url: null, assemblies: [] }))).toEqual({
      available: true,
      href: null,
      reason: null,
    });
  });

  it("keeps an embedded graph unavailable when its plugin is unhealthy", () => {
    expect(resolveEmbeddedPlugin(capability({ healthy: false, reason: "upstream_timeout" }))).toEqual({
      available: false,
      href: null,
      reason: "upstream_timeout",
    });
  });
});
