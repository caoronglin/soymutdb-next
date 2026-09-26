/**
 * Contract tests for the postMessage bridge and deep-link utilities.
 *
 * Exercises the shipped modules directly (Node 24 strips the TypeScript types),
 * so the assertions cover real behaviour rather than source-text patterns.
 *
 * Run with: node --test bridge-contract.test.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BRIDGE_SOURCE_BROWSER,
  BRIDGE_SOURCE_JBROWSE,
  BRIDGE_VERSION,
  parsePortalMessage,
  postToParent,
} from "./src/bridge.ts";
import {
  buildDeepLink,
  calculateViewWindow,
  formatLocus,
  parseDeepLink,
  parseLocus,
  pointToLocus,
  toOneBased,
  toZeroBased,
} from "./src/deep-link.ts";

const BASE = "https://portal.test/browser";
const PORTAL_ORIGIN = "https://portal.test";

/** Swap globalThis.window for the duration of fn, restoring it afterwards. */
function withWindow(value, fn) {
  const had = Object.prototype.hasOwnProperty.call(globalThis, "window");
  const previous = globalThis.window;
  if (value === undefined) {
    delete globalThis.window;
  } else {
    globalThis.window = value;
  }
  try {
    return fn();
  } finally {
    if (had) {
      globalThis.window = previous;
    } else {
      delete globalThis.window;
    }
  }
}

/** Capture console.warn calls emitted while fn runs. */
function warnsOf(fn) {
  const calls = [];
  const original = console.warn;
  console.warn = (...args) => {
    calls.push(args.map((arg) => String(arg)).join(" "));
  };
  try {
    fn();
  } finally {
    console.warn = original;
  }
  return calls;
}

// ---------------------------------------------------------------------------
// Deep-link round-trip
// ---------------------------------------------------------------------------

test("buildDeepLink/parseDeepLink round-trips locus, tracks, assembly and release", () => {
  const params = {
    locus: "chr01:1-1000000",
    tracks: ["genes", "variants"],
    assembly: "Wm82v4.0",
    release: "v4.0",
  };
  const url = buildDeepLink(params, BASE);
  assert.equal(url.startsWith(`${BASE}?`), true);
  // The app parses window.location.search (a leading "?" string).
  assert.deepEqual(parseDeepLink(new URL(url).search), params);
});

test("parseDeepLink accepts the legacy loc alias and prefers canonical locus", () => {
  assert.deepEqual(parseDeepLink("?loc=chr05:10-20"), { locus: "chr05:10-20" });
  assert.deepEqual(parseDeepLink("?locus=chr01:1-5&loc=chr99:9-9"), {
    locus: "chr01:1-5",
  });
});

test("parseDeepLink supports repeated and comma-separated tracks", () => {
  assert.deepEqual(parseDeepLink("?tracks=genes,variants&tracks=sv"), {
    tracks: ["genes", "variants", "sv"],
  });
  assert.deepEqual(parseDeepLink("?tracks=%20genes%20,%20variants%20"), {
    tracks: ["genes", "variants"],
  });
  assert.deepEqual(parseDeepLink("?tracks="), {});
});

test("portalOrigin is parsed for embedding but never emitted by buildDeepLink", () => {
  assert.deepEqual(parseDeepLink("?portalOrigin=https%3A%2F%2Fportal.test"), {
    portalOrigin: PORTAL_ORIGIN,
  });
  const url = buildDeepLink({ locus: "chr1:1-5", portalOrigin: PORTAL_ORIGIN }, BASE);
  assert.equal(url.includes("portalOrigin"), false);
  assert.equal(new URL(url).searchParams.get("portalOrigin"), null);
});

test("parseDeepLink accepts URLSearchParams records and empty input builds a bare URL", () => {
  const search = new URLSearchParams("locus=chr1:1-5&assembly=v5");
  assert.deepEqual(parseDeepLink(search), { locus: "chr1:1-5", assembly: "v5" });
  assert.deepEqual(parseDeepLink({ locus: "chr2:3-4", tracks: ["a", "b"], release: "v4" }), {
    locus: "chr2:3-4",
    tracks: ["a", "b"],
    release: "v4",
  });
  assert.equal(buildDeepLink({}, BASE), BASE);
});

test("parseDeepLink resolves an absolute URL against the embedding window origin", () => {
  withWindow({ location: { origin: PORTAL_ORIGIN } }, () => {
    assert.deepEqual(
      parseDeepLink("https://portal.test/browser?locus=chr01:1-1000&release=v4.0"),
      { locus: "chr01:1-1000", release: "v4.0" },
    );
  });
});

test("parseLocus/formatLocus round-trip 1-based inclusive loci", () => {
  assert.deepEqual(parseLocus("chr01:1,000-1,000,000"), {
    refName: "chr01",
    start: 1000,
    end: 1000000,
  });
  assert.deepEqual(parseLocus("chr01:1..1000"), { refName: "chr01", start: 1, end: 1000 });
  assert.equal(parseLocus("not-a-locus"), null);
  assert.equal(formatLocus({ refName: "chr01", start: 1, end: 1000 }), "chr01:1-1000");
  assert.equal(formatLocus(parseLocus("chr01:1..1000")), "chr01:1-1000");
});

// ---------------------------------------------------------------------------
// Coordinate conversions
// ---------------------------------------------------------------------------

test("toZeroBased converts 1-based inclusive to 0-based half-open", () => {
  assert.deepEqual(toZeroBased(1, 1000), [0, 1000]);
  assert.deepEqual(toZeroBased(5, 5), [4, 5]); // single base -> width 1
  assert.deepEqual(toZeroBased(0, 10), [0, 10]); // clamps non-positive start
  assert.deepEqual(toZeroBased(-5, 10), [0, 10]);
});

test("toOneBased converts 0-based half-open back to 1-based inclusive", () => {
  assert.deepEqual(toOneBased(0, 1000), [1, 1000]);
  assert.deepEqual(toOneBased(4, 5), [5, 5]);
});

test("coordinate conversions round-trip for valid 1-based intervals", () => {
  for (const [start, end] of [
    [1, 1],
    [1, 1000],
    [10, 20],
    [500, 500],
  ]) {
    assert.deepEqual(toOneBased(...toZeroBased(start, end)), [start, end]);
  }
});

test("calculateViewWindow and pointToLocus stay 1-based inclusive", () => {
  assert.deepEqual(calculateViewWindow(1000, 2000), { start: 800, end: 2200 });
  assert.deepEqual(calculateViewWindow(1, 1), { start: 1, end: 51 });
  assert.equal(pointToLocus("chr1", 3, 500), "chr1:1-503");
  assert.equal(pointToLocus("chr1", 1000000, 500), "chr1:999500-1000500");
});

// ---------------------------------------------------------------------------
// Bridge envelope validation
// ---------------------------------------------------------------------------

test("bridge constants pin the shared source/version", () => {
  assert.equal(BRIDGE_SOURCE_BROWSER, "soymutdb-browser");
  assert.equal(BRIDGE_SOURCE_JBROWSE, "soymutdb-jbrowse");
  assert.equal(BRIDGE_VERSION, 1);
});

test("parsePortalMessage accepts a valid init envelope from the portal origin", () => {
  const data = {
    source: BRIDGE_SOURCE_BROWSER,
    version: BRIDGE_VERSION,
    type: "init",
    payload: { assembly: "Wm82v4.0", locus: "chr01:1-1000" },
  };
  const parsed = parsePortalMessage({ origin: PORTAL_ORIGIN, data }, PORTAL_ORIGIN);
  assert.deepEqual(parsed, data);
});

test("parsePortalMessage rejects a message from an unexpected origin", () => {
  const data = { source: BRIDGE_SOURCE_BROWSER, version: BRIDGE_VERSION, type: "init" };
  const warns = warnsOf(() => {
    assert.equal(
      parsePortalMessage({ origin: "https://evil.test", data }, PORTAL_ORIGIN),
      null,
    );
  });
  assert.equal(warns.length, 1);
  assert.match(warns[0], /unexpected origin/i);
});

test("parsePortalMessage rejects malformed payloads", () => {
  const payloads = [
    null,
    undefined,
    "init",
    42,
    {},
    { source: BRIDGE_SOURCE_BROWSER, version: BRIDGE_VERSION },
    { source: BRIDGE_SOURCE_BROWSER, version: BRIDGE_VERSION, type: 7 },
  ];
  for (const data of payloads) {
    const warns = warnsOf(() => {
      assert.equal(parsePortalMessage({ origin: PORTAL_ORIGIN, data }, PORTAL_ORIGIN), null);
    });
    assert.equal(warns.length, 1, `expected one warning for ${JSON.stringify(data)}`);
    assert.match(warns[0], /malformed/i);
  }
});

test("parsePortalMessage rejects the wrong source or version", () => {
  const payloads = [
    { source: BRIDGE_SOURCE_JBROWSE, version: BRIDGE_VERSION, type: "init" },
    { source: "soymutdb-something-else", version: BRIDGE_VERSION, type: "init" },
    { version: BRIDGE_VERSION, type: "init" },
    { source: BRIDGE_SOURCE_BROWSER, version: 2, type: "init" },
    { source: BRIDGE_SOURCE_BROWSER, version: "1", type: "init" },
    { source: BRIDGE_SOURCE_BROWSER, type: "init" },
  ];
  for (const data of payloads) {
    const warns = warnsOf(() => {
      assert.equal(parsePortalMessage({ origin: PORTAL_ORIGIN, data }, PORTAL_ORIGIN), null);
    });
    assert.equal(warns.length, 1, `expected one warning for ${JSON.stringify(data)}`);
    assert.match(warns[0], /invalid bridge message/i);
  }
});

// ---------------------------------------------------------------------------
// Portal-origin policy: outbound behaviour / standalone
// ---------------------------------------------------------------------------

test("postToParent is a no-op when there is no window (standalone tab)", () => {
  withWindow(undefined, () => {
    assert.doesNotThrow(() => postToParent({ type: "ready" }, PORTAL_ORIGIN));
  });
});

test("postToParent is a no-op when window.parent === window (top-level tab)", () => {
  const win = { posted: [] };
  win.postMessage = (...args) => win.posted.push(args);
  win.parent = win;
  withWindow(win, () => postToParent({ type: "ready" }, PORTAL_ORIGIN));
  assert.equal(win.posted.length, 0);
});

test("postToParent stamps source/version and targets the portal origin when embedded", () => {
  for (const type of ["ready", "error", "locus-change"]) {
    const calls = [];
    const parent = { postMessage: (...args) => calls.push(args) };
    withWindow({ parent }, () => {
      postToParent({ type, payload: { locus: "chr1:1-5" } }, PORTAL_ORIGIN);
    });
    assert.equal(calls.length, 1, `expected a post for ${type}`);
    const [message, targetOrigin] = calls[0];
    assert.equal(targetOrigin, PORTAL_ORIGIN);
    assert.deepEqual(message, {
      source: BRIDGE_SOURCE_JBROWSE,
      version: BRIDGE_VERSION,
      type,
      payload: { locus: "chr1:1-5" },
    });
  }
});
