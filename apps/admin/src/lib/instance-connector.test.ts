import { beforeEach, describe, expect, it, vi } from "vitest";

import type { SpeciesInstance } from "@soymutdb/api-client";
import {
  createInstanceConnector,
  RemoteAdministrationDisabledError,
  remoteAdministrationEnabled,
} from "./instance-connector";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    checkSpeciesInstanceHealth: vi.fn().mockResolvedValue({
      id: 1,
      code: "local",
      connection_state: "healthy",
      checked_at: "2026-09-26T00:00:00Z",
      last_checked_at: null,
      last_error_at: null,
      is_stale: false,
      error_code: null,
      remote_management: "local",
    }),
  };
});

const LOCAL: SpeciesInstance = {
  id: 1,
  code: "local",
  name: "Local",
  species: "Glycine max",
  api_base_url: "http://localhost:8010",
  jbrowse_base_url: null,
  portal_base_url: null,
  site_url: null,
  is_enabled: true,
  is_local: true,
  connection_state: "healthy",
  last_checked_at: null,
  last_error_at: null,
  is_stale: false,
  remote_management: "local",
  notes: null,
  created_at: "2026-09-25T00:00:00Z",
  updated_at: "2026-09-25T00:00:00Z",
};

const REMOTE: SpeciesInstance = {
  ...LOCAL,
  id: 2,
  code: "peer",
  name: "Peer",
  api_base_url: "https://peer.example.org",
  is_local: false,
  remote_management: "registration_only",
};

beforeEach(() => {
  vi.unstubAllEnvs();
});

describe("instance connectors", () => {
  it("treats the local instance as writable and probes it through the API", async () => {
    const connector = createInstanceConnector(LOCAL);

    expect(connector.kind).toBe("local");
    expect(connector.writePolicy).toBe("local_managed");
    expect(connector.writable).toBe(true);
    await connector.read.probeHealth();
  });

  it("keeps a remote registration read-only regardless of the build flag", () => {
    for (const enabled of [false, true]) {
      const connector = createInstanceConnector(REMOTE, { remoteEnabled: enabled });

      expect(connector.kind).toBe("remote");
      expect(connector.writePolicy).toBe("registration_only");
      expect(connector.writable).toBe(false);
      expect(enabled || !enabled).toBe(true);
    }
  });

  it("refuses remote administration until the trust channel is started", () => {
    const disabled = createInstanceConnector(REMOTE, { remoteEnabled: false });
    expect(() => disabled.administer()).toThrow(RemoteAdministrationDisabledError);

    // Even with the deployment flag on, the write path is not implemented: the
    // flag records readiness, it does not open an unaudited channel.
    const flagged = createInstanceConnector(REMOTE, { remoteEnabled: true });
    expect(() => flagged.administer()).toThrow(RemoteAdministrationDisabledError);
  });

  it("never routes local administration through the connector", () => {
    const connector = createInstanceConnector(LOCAL);
    expect(() => connector.administer()).toThrow(RemoteAdministrationDisabledError);
  });

  it("defaults the remote switch to off in the build environment", () => {
    expect(remoteAdministrationEnabled()).toBe(false);
  });
});
