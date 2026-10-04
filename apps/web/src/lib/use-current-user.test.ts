/**
 * Authorisation is read from the server, not from a client-side role table.
 *
 * `GET /auth/me` answers with `effective_roles` — the session's grants
 * expanded from `apps/api/app/core/security.py::_ROLE_GRANTS`. The portal used
 * to keep its own list (`researcher`, `administrator`) and that copy had
 * already drifted: seven roles the server lets run analyses were refused here.
 *
 * The cases below pin the resolution order, including the one that matters
 * most: when the field is missing the hook must fail *closed* for a viewer and
 * must not invent a grant the server never sent.
 */
import { describe, expect, it } from "vitest";

import { grantsResearcher, type CurrentUser } from "./use-current-user";

const base: CurrentUser = {
  id: "u1",
  username: "u",
  email: "u@example.org",
  is_active: true,
  is_superuser: false,
};

describe("effective_roles drives the analyses capability", () => {
  it("grants a curator through the server's expansion", () => {
    expect(
      grantsResearcher({
        ...base,
        role_name: "curator",
        effective_roles: ["viewer", "researcher", "curator"],
      }),
    ).toBe(true);
  });

  it("refuses a viewer even though the role string is present", () => {
    expect(grantsResearcher({ ...base, role_name: "viewer", effective_roles: ["viewer"] })).toBe(false);
  });

  it("trusts an empty effective_roles over the role name", () => {
    // The server is the authority: if it says "no grants", a stale
    // role_name must not promote the session.
    expect(grantsResearcher({ ...base, role_name: "researcher", effective_roles: [] })).toBe(false);
  });

  it("keeps a superuser allowed regardless of the expansion", () => {
    expect(grantsResearcher({ ...base, is_superuser: true, effective_roles: [] })).toBe(true);
  });

  it("falls back to the grant shape when the API predates the field", () => {
    expect(grantsResearcher({ ...base, role_name: "content_editor" })).toBe(true);
    expect(grantsResearcher({ ...base, role_name: "auditor" })).toBe(true);
    expect(grantsResearcher({ ...base, role_name: "viewer" })).toBe(false);
  });

  it("fails closed when neither the field nor a role is present", () => {
    expect(grantsResearcher({ ...base })).toBe(false);
    expect(grantsResearcher({ ...base, role_name: null })).toBe(false);
  });

  it("stays aligned with the backend grant table for every role", () => {
    // Mirrors apps/api/app/core/security.py::TestEffectiveRoles: viewer is the
    // only role that does not satisfy require_role(RESEARCHER).
    const grants = {
      viewer: ["viewer"],
      researcher: ["viewer", "researcher"],
      curator: ["viewer", "researcher", "curator"],
      data_manager: ["viewer", "researcher", "curator", "data_manager"],
      track_manager: ["viewer", "researcher", "curator", "track_manager"],
      blast_manager: ["viewer", "researcher", "curator", "blast_manager"],
      seed_manager: ["viewer", "researcher", "curator", "seed_manager"],
      content_editor: ["viewer", "researcher", "curator", "content_editor"],
      auditor: ["viewer", "researcher", "curator", "auditor"],
      administrator: [
        "viewer",
        "researcher",
        "curator",
        "data_manager",
        "track_manager",
        "blast_manager",
        "seed_manager",
        "content_editor",
        "auditor",
        "administrator",
      ],
    } as const;
    for (const [role, effective] of Object.entries(grants)) {
      expect(grantsResearcher({ ...base, role_name: role, effective_roles: [...effective] })).toBe(
        role !== "viewer",
      );
    }
  });
});