import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BRIDGE_SOURCE_BROWSER,
  BRIDGE_SOURCE_JBROWSE,
  BRIDGE_TYPES,
  BRIDGE_VERSION,
  isBridgeMessageType,
  parsePortalMessage,
  postToParent,
  type BridgeEnvelope,
} from "../../../../apps/jbrowse/src/bridge";

const PORTAL_ORIGIN = "https://portal.test";

function asEvent(origin: string, data: unknown): MessageEvent {
  return { origin, data } as unknown as MessageEvent;
}

describe("ablation scenario 10: postMessage bridge", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("emits a canonical envelope and parses an inbound envelope round-trip", () => {
    const posted: unknown[][] = [];
    const win = { parent: { postMessage: (...args: unknown[]) => posted.push(args) } };
    vi.stubGlobal("window", win);

    postToParent(
      { type: "locus-change", payload: { assembly: "v4", locus: "chr01:1-10" } },
      PORTAL_ORIGIN,
    );

    expect(posted).toHaveLength(1);
    const [message, targetOrigin] = posted[0] as [BridgeEnvelope, string];
    expect(targetOrigin).toBe(PORTAL_ORIGIN);
    expect(message.source).toBe(BRIDGE_SOURCE_JBROWSE);
    expect(message.version).toBe(BRIDGE_VERSION);

    const parsed = parsePortalMessage(
      asEvent(PORTAL_ORIGIN, {
        source: BRIDGE_SOURCE_BROWSER,
        version: BRIDGE_VERSION,
        type: "init",
        payload: message.payload,
      }),
      PORTAL_ORIGIN,
    );
    expect(parsed).toEqual({
      source: BRIDGE_SOURCE_BROWSER,
      version: BRIDGE_VERSION,
      type: "init",
      payload: { assembly: "v4", locus: "chr01:1-10" },
    });
  });

  it("accepts every documented type and rejects a type outside the allow-list", () => {
    const warnings: string[] = [];
    vi.spyOn(console, "warn").mockImplementation((...args: unknown[]) => {
      warnings.push(args.map((arg) => String(arg)).join(" "));
    });

    for (const type of BRIDGE_TYPES) {
      const parsed = parsePortalMessage(
        asEvent(PORTAL_ORIGIN, {
          source: BRIDGE_SOURCE_BROWSER,
          version: BRIDGE_VERSION,
          type,
        }),
        PORTAL_ORIGIN,
      );
      expect(parsed?.type).toBe(type);
    }
    expect(warnings).toHaveLength(0);

    const rejected = parsePortalMessage(
      asEvent(PORTAL_ORIGIN, {
        source: BRIDGE_SOURCE_BROWSER,
        version: BRIDGE_VERSION,
        type: "locus-changed",
      }),
      PORTAL_ORIGIN,
    );
    expect(rejected).toBeNull();
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toMatch(/malformed/i);
    expect(isBridgeMessageType("init")).toBe(true);
    expect(isBridgeMessageType("locus-changed")).toBe(false);
  });
});
