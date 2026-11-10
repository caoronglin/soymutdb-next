/**
 * The session state machine is the only place that decides what a session
 * means. These cases are the W3 table: restoring / anonymous / authenticated /
 * expired / error, plus the two separations that keep failing — a network error
 * is not an authorization answer, and a public page is not bounced.
 */
import { describe, expect, it } from "vitest";
import { ApiError } from "@soymutdb/api-client";

import {
  INITIAL_SESSION,
  isPublicPath,
  snapshotFor,
  statusFromProbeFailure,
  statusFromRestore,
} from "./session";

describe("boot restore", () => {
  it("starts in restoring with no personal reads allowed", () => {
    expect(INITIAL_SESSION.status).toBe("restoring");
    expect(INITIAL_SESSION.canQueryPersonal).toBe(false);
    expect(INITIAL_SESSION.canAct).toBe(false);
  });

  it("authenticates and opens personal reads on a token", () => {
    const next = statusFromRestore({ status: "authenticated" }, INITIAL_SESSION);
    expect(next.status).toBe("authenticated");
    expect(next.canQueryPersonal).toBe(true);
    expect(next.sessionId).toBe(INITIAL_SESSION.sessionId + 1);
  });

  it("treats no cookie as anonymous, not as an error", () => {
    const next = statusFromRestore({ status: "anonymous" }, INITIAL_SESSION);
    expect(next.status).toBe("anonymous");
    expect(next.canQueryPersonal).toBe(false);
    expect(next.error).toBeUndefined();
  });

  it("keeps a transport failure retryable and distinct from anonymous", () => {
    const failure = new ApiError("upstream unavailable", 503, "unavailable");
    const next = statusFromRestore({ status: "error", error: failure }, INITIAL_SESSION);
    expect(next.status).toBe("error");
    expect(next.error).toBe(failure);
    expect(next.canQueryPersonal).toBe(false);
  });

  it("does not decide anything when another transition owns the state", () => {
    const current = snapshotFor("expired", 4);
    expect(statusFromRestore({ status: "superseded" }, current)).toBe(current);
  });
});

describe("personal read failure", () => {
  it("reads a 401 as an expired session once one existed", () => {
    const authenticated = snapshotFor("authenticated", 2);
    const next = statusFromProbeFailure(new ApiError("gone", 401, "unauthorized"), authenticated);
    expect(next.status).toBe("expired");
    expect(next.canAct).toBe(false);
  });

  it("reads a 401 as anonymous when no session was ever established", () => {
    const next = statusFromProbeFailure(new ApiError("gone", 401, "unauthorized"), INITIAL_SESSION);
    expect(next.status).toBe("anonymous");
  });

  it("never turns a network failure into a permission verdict", () => {
    const authenticated = snapshotFor("authenticated", 2);
    for (const failure of [
      new TypeError("Failed to fetch"),
      new ApiError("gateway", 502, "bad_gateway"),
      new ApiError("server", 500, "internal"),
    ]) {
      const next = statusFromProbeFailure(failure, authenticated);
      expect(next.status).toBe("error");
      expect(next.canQueryPersonal).toBe(false);
    }
  });
});

describe("public path detection", () => {
  it("keeps browsing pages out of the forced sign-in path", () => {
    for (const path of ["/", "/search", "/genes/Glyma.01G000100", "/news", "/seed-request"]) {
      expect(isPublicPath(path)).toBe(true);
    }
  });

  it("treats account-only routes as gated", () => {
    expect(isPublicPath("/login")).toBe(false);
  });

  it("honours the deployment base path", () => {
    expect(isPublicPath("/portal/search", "/portal/")).toBe(true);
  });
});