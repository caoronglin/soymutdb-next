/**
 * Contract tests for the release-scoped context of the genome browser.
 *
 * The API resolves every public query inside one published release, and
 * `/tracks/jbrowse-config` refuses an `assembly_id` that does not belong to
 * the release it is asked for. These tests pin the behaviour that keeps the
 * assembly list and the track configuration inside the *same* release, and
 * that an unusable release never falls back to the active one.
 *
 * Run with: node --test release-context.test.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  assembliesRequestParams,
  configRequestParams,
  releaseScopedParams,
  resolveContextStatus,
  resolveReleaseScope,
} from "./src/release-context.ts";

// ---------------------------------------------------------------------------
// resolveReleaseScope
// ---------------------------------------------------------------------------

test("an absent release leaves the choice to the server", () => {
  for (const value of [undefined, null, "", "   "]) {
    const scope = resolveReleaseScope(value);
    assert.equal(scope.invalid, false, `release ${JSON.stringify(value)} must stay usable`);
    assert.equal(scope.releaseId, undefined);
    assert.deepEqual(releaseScopedParams(scope), {});
  }
});

test("a numeric release id is pinned to every request", () => {
  const scope = resolveReleaseScope("7");
  assert.equal(scope.invalid, false);
  assert.equal(scope.releaseId, "7");
  assert.deepEqual(releaseScopedParams(scope), { release_id: "7" });
});

test("a release id that cannot address a release is invalid, not ignored", () => {
  for (const value of ["v4.0", "abc", "0", "-1", "1.5", "7;drop"]) {
    const scope = resolveReleaseScope(value);
    assert.equal(scope.invalid, true, `release ${value} must be rejected`);
    assert.equal(scope.releaseId, undefined);
  }
});

// ---------------------------------------------------------------------------
// Request parameters
// ---------------------------------------------------------------------------

test("the assembly list and the configuration are read from the same release", () => {
  const scope = resolveReleaseScope("7");
  const assemblies = assembliesRequestParams(scope);
  const config = configRequestParams(scope, 42);
  assert.deepEqual(assemblies, { release_id: "7" });
  assert.deepEqual(config, { assembly_id: "42", release_id: "7" });
  assert.equal(config.release_id, assemblies.release_id);
});

test("release A and release B never share a request scope", () => {
  const releaseA = resolveReleaseScope("4");
  const releaseB = resolveReleaseScope("9");
  assert.notEqual(releaseA.releaseId, releaseB.releaseId);
  assert.deepEqual(assembliesRequestParams(releaseA), { release_id: "4" });
  assert.deepEqual(assembliesRequestParams(releaseB), { release_id: "9" });
  assert.deepEqual(configRequestParams(releaseA, 1), { assembly_id: "1", release_id: "4" });
  assert.deepEqual(configRequestParams(releaseB, 2), { assembly_id: "2", release_id: "9" });
});

test("an invalid release never falls back to the active release", () => {
  const scope = resolveReleaseScope("v4.0");
  assert.equal(scope.invalid, true);
  // No release id is emitted: the caller must refuse the request instead of
  // asking for the active release under an invalid deep link.
  assert.deepEqual(releaseScopedParams(scope), {});
  assert.deepEqual(assembliesRequestParams(scope), {});
  assert.deepEqual(configRequestParams(scope, 3), { assembly_id: "3" });
});

// ---------------------------------------------------------------------------
// resolveContextStatus
// ---------------------------------------------------------------------------

test("a healthy context reports no failure", () => {
  const status = resolveContextStatus({
    assembly: "Wm82.a4.v1",
    assemblyFound: true,
    configComplete: true,
  });
  assert.equal(status.status, "ok");
  assert.equal(status.message, "");
});

test("an unusable release is reported instead of silently using the active one", () => {
  const status = resolveContextStatus({ releaseInvalid: true, assembly: "Wm82.a4.v1" });
  assert.equal(status.status, "invalid-release");
  assert.match(status.message, /release id/i);
});

test("an assembly outside the selected release is an error, never a substitution", () => {
  const status = resolveContextStatus({
    assembly: "Wm82.a4.v1",
    assemblyFound: false,
  });
  assert.equal(status.status, "assembly-not-in-release");
  assert.match(status.message, /Wm82\.a4\.v1/);
});

test("an unavailable assembly list is reported as such", () => {
  const status = resolveContextStatus({
    assembly: "Wm82.a4.v1",
    assembliesError: true,
  });
  assert.equal(status.status, "assemblies-unavailable");
  assert.ok(status.message.length > 0);
});

test("an unavailable configuration is reported as such", () => {
  const status = resolveContextStatus({
    assembly: "Wm82.a4.v1",
    assemblyFound: true,
    configError: true,
  });
  assert.equal(status.status, "config-unavailable");
  assert.ok(status.message.length > 0);
});

test("a deep link without an assembly reports the missing assembly", () => {
  const status = resolveContextStatus({ assembly: "" });
  assert.equal(status.status, "no-assembly");
  assert.ok(status.message.length > 0);
});
