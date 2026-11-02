/**
 * Release-scoped context for the standalone genome browser.
 *
 * The API resolves every public query inside exactly one published release:
 * `/genes/assemblies` lists the assemblies of that release and
 * `/tracks/jbrowse-config` refuses an `assembly_id` that does not belong to
 * the release it is asked for. The two requests must therefore name the *same*
 * release, otherwise the assembly id resolved from one request is used to ask
 * the other for a configuration — an assembly id of a different release is
 * never a valid identity for the requested one.
 *
 * The release comes from the deep link and is never guessed at runtime:
 *
 *   - absent     → the request carries no release and the server resolves the
 *                  active published release. That is the server's own
 *                  authoritative answer, not a client-side guess.
 *   - a valid id → every request is pinned to that release, so a job or a
 *                  shared link from an older release keeps reading that
 *                  release's assemblies and tracks.
 *   - unusable   → the context is invalid. No request may be sent: dropping
 *                  the pin would silently resolve the *active* release and
 *                  show its coordinates under the requested one.
 */

/** A release id is a positive integer; anything else cannot address a release. */
const POSITIVE_INTEGER = /^[1-9][0-9]*$/;

export interface ReleaseScope {
    /** The release id every request is pinned to; `undefined` lets the server decide. */
    readonly releaseId?: string;
    /** The deep link carried a release that cannot address a release. */
    readonly invalid: boolean;
}

/**
 * Resolve the deep link's release into a scope.
 *
 * @param release The raw `release` deep-link parameter.
 */
export function resolveReleaseScope(release: string | null | undefined): ReleaseScope {
    if (release == null) return { invalid: false };
    const trimmed = release.trim();
    if (trimmed === "") return { invalid: false };
    if (!POSITIVE_INTEGER.test(trimmed)) return { invalid: true };
    return { releaseId: trimmed, invalid: false };
}

/**
 * The query parameters that pin a request to the scoped release.
 *
 * An invalid scope yields no parameters *and* must not be used to build a
 * request at all — the caller checks `scope.invalid` first.
 */
export function releaseScopedParams(scope: ReleaseScope): { release_id?: string } {
    return scope.releaseId ? { release_id: scope.releaseId } : {};
}

/** Parameters of the assemblies request for the scoped release. */
export function assembliesRequestParams(scope: ReleaseScope): { release_id?: string } {
    return releaseScopedParams(scope);
}

/**
 * Parameters of the configuration request.
 *
 * The assembly id and the release id are taken from the same scope, so the
 * configuration can only ever be read for the release the assembly list came
 * from.
 */
export function configRequestParams(
    scope: ReleaseScope,
    assemblyId: string | number,
): { assembly_id: string; release_id?: string } {
    return { assembly_id: String(assemblyId), ...releaseScopedParams(scope) };
}

/** Why the genome browser cannot show a trustworthy view. */
export type JBrowseContextStatus =
    | "ok"
    | "invalid-release"
    | "assemblies-unavailable"
    | "no-assembly"
    | "assembly-not-in-release"
    | "config-unavailable"
    | "incomplete-config";

export interface ContextStatusInput {
    /** The deep link's release could not address a release. */
    readonly releaseInvalid?: boolean;
    /** The assembly named by the deep link (empty when none was named). */
    readonly assembly?: string;
    /** The assemblies request failed. */
    readonly assembliesError?: boolean;
    /** The named assembly was found in the release's assembly list. */
    readonly assemblyFound?: boolean;
    /** The configuration request failed. */
    readonly configError?: boolean;
    /** The configuration payload carried a complete reference assembly. */
    readonly configComplete?: boolean;
}

export interface ContextStatus {
    readonly status: JBrowseContextStatus;
    /** A human-readable reason; empty when the status is `ok`. */
    readonly message: string;
}

/**
 * Explain whether a trustworthy view can be shown.
 *
 * Every branch fails closed: an unknown assembly is never substituted with
 * the release's default, and an unusable release is never downgraded to the
 * active one. The reason is shown instead of a viewer, so a reader can tell a
 * missing context apart from a broken deployment.
 */
export function resolveContextStatus(input: ContextStatusInput): ContextStatus {
    if (input.releaseInvalid) {
        return {
            status: "invalid-release",
            message: "The selected release is not a valid release id.",
        };
    }
    if (input.assembliesError) {
        return {
            status: "assemblies-unavailable",
            message: "The assembly list of the selected release is unavailable.",
        };
    }
    const assembly = (input.assembly ?? "").trim();
    if (assembly === "") {
        return {
            status: "no-assembly",
            message: "No assembly could be resolved for the selected release.",
        };
    }
    if (!input.assemblyFound) {
        return {
            status: "assembly-not-in-release",
            message: `Assembly "${assembly}" is not part of the selected released genome.`,
        };
    }
    if (input.configError) {
        return {
            status: "config-unavailable",
            message: "The release-scoped JBrowse configuration is unavailable.",
        };
    }
    if (input.configComplete) {
        return { status: "ok", message: "" };
    }
    return {
        status: "incomplete-config",
        message: "The JBrowse configuration did not include a complete reference assembly.",
    };
}
