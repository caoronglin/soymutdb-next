/**
 * Instance connectors: one read-only capability surface for local and remote.
 *
 * "One admin panel, many instances" is a trust model before it is a feature
 * (plan §D): the remote administration channel is **implemented as an
 * interface but not started**. This module defines the contract and the local
 * implementation, and it refuses remote administration until deployment-side
 * trust configuration (allowlisted HTTPS origins, per-instance service
 * credentials, audited routing) and dual-instance testing are complete.
 *
 * What is allowed today for a remote registration:
 *  - the bounded liveness probe (`/api/v1/health/live`), enforced server-side
 *    by the deployment allowlist; and
 *  - nothing else. There is no proxy, no remote write, and no browser-side
 *    remote credential.
 */
import {
  checkSpeciesInstanceHealth,
  type SpeciesInstance,
  type SpeciesInstanceHealth,
} from "@soymutdb/api-client";

export type InstanceKind = "local" | "remote";
export type InstanceWritePolicy = "local_managed" | "registration_only";

/** Error raised when a disabled remote-administration capability is used. */
export class RemoteAdministrationDisabledError extends Error {
  readonly code = "remote_administration_disabled";

  constructor(message = "Remote instance administration is disabled") {
    super(message);
    this.name = "RemoteAdministrationDisabledError";
  }
}

/** Deployment switch for the (not yet started) remote administration channel. */
export function remoteAdministrationEnabled(): boolean {
  return import.meta.env.VITE_REMOTE_INSTANCES_ENABLED === "true";
}

export interface InstanceReadCapabilities {
  /** Bounded liveness probe; never proxies admin calls and never sends identity. */
  probeHealth(): Promise<SpeciesInstanceHealth>;
}

export interface InstanceConnector {
  readonly kind: InstanceKind;
  readonly instance: SpeciesInstance;
  readonly writePolicy: InstanceWritePolicy;
  /** True only when the console may mutate the instance's own data. */
  readonly writable: boolean;
  readonly read: InstanceReadCapabilities;
  /**
   * Remote administration entry point. Always refuses while the trust
   * configuration and dual-instance testing are pending, regardless of the
   * build flag — the flag only records readiness, it does not implement a
   * remote write path.
   */
  administer(): never;
}

export interface ConnectorOptions {
  remoteEnabled?: boolean;
}

/** Build the connector for one registered instance. */
export function createInstanceConnector(
  instance: SpeciesInstance,
  options: ConnectorOptions = {},
): InstanceConnector {
  const remoteEnabled = options.remoteEnabled ?? remoteAdministrationEnabled();

  if (instance.is_local) {
    return {
      kind: "local",
      instance,
      writePolicy: "local_managed",
      writable: true,
      read: {
        probeHealth: () => checkSpeciesInstanceHealth(instance.id),
      },
      administer() {
        // Local administration is the console's own API; it is not routed
        // through this interface.
        throw new RemoteAdministrationDisabledError(
          "Local administration runs through the console API, not the instance connector",
        );
      },
    };
  }

  return {
    kind: "remote",
    instance,
    writePolicy: "registration_only",
    writable: false,
    read: {
      probeHealth: () => checkSpeciesInstanceHealth(instance.id),
    },
    administer() {
      throw new RemoteAdministrationDisabledError(
        remoteEnabled
          ? "Remote administration is enabled by configuration but the trust channel is not started"
          : "Remote administration is disabled until trust configuration and dual-instance testing are complete",
      );
    },
  };
}
