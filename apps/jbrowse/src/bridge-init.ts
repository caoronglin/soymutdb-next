import { parseLocusList } from "./deep-link.ts";

/** Use JBrowse's public navigation methods, including cross-chromosome setup. */
export async function navigateBrowserView<AssemblyModel extends { name: string }>(
  view: {
    navToLocString(input: string, assembly?: string): unknown;
    navToSearchString(query: { input: string; assembly: AssemblyModel }): unknown;
    /** JBrowse 2 exposes the viewport as a (possibly multi-region) string. */
    visibleLocStrings?: string;
  },
  input: string,
  assembly?: string,
  assemblyManager?: { waitForAssembly(name: string): Promise<AssemblyModel | undefined> },
): Promise<string | undefined> {
  if (parseLocusList(input)) await view.navToLocString(input, assembly);
  else {
    if (!assembly || !assemblyManager) throw new Error("Reference assembly is not ready");
    const model = await assemblyManager.waitForAssembly(assembly);
    if (!model) throw new Error("Reference assembly is not available");
    await view.navToSearchString({ input, assembly: model });
  }
  // A feature query is not a genomic locus. Only emit the actual visible span.
  return view.visibleLocStrings || undefined;
}

/** Portal intent is retained independently of asynchronous release/config loading. */
export interface BrowserInitState {
  release?: string;
  assembly: string;
  tracks?: string[];
  locus?: string;
}

export function planPortalInit(
  current: BrowserInitState,
  payload: { release?: unknown; assembly?: unknown; tracks?: unknown; locus?: unknown },
  hasView: boolean,
): BrowserInitState & { rebuild: boolean } {
  const text = (value: unknown) => typeof value === "string" && value.trim() ? value.trim() : undefined;
  const release = text(payload.release) ?? current.release;
  const assembly = text(payload.assembly) ?? current.assembly;
  const scopeChanged = release !== current.release || assembly !== current.assembly;
  // Old coordinates cannot be relabelled with a different release/assembly.
  const locus = text(payload.locus) ?? (scopeChanged ? undefined : current.locus);
  // Bridge v1 historically sends [] for an unspecified selection: retain that
  // compatibility. Unspecified tracks adopt defaults on a scope switch.
  const supplied = Array.isArray(payload.tracks)
    ? [...new Set(payload.tracks.filter((id): id is string => typeof id === "string" && id.length > 0))]
    : undefined;
  const requested = supplied?.length ? supplied : scopeChanged ? undefined : current.tracks;
  const signature = (ids: string[] | undefined) => ids == null ? undefined : JSON.stringify([...new Set(ids)].sort());
  const sameTracks = signature(requested) === signature(current.tracks);
  const tracks = sameTracks ? current.tracks : requested;
  return { release, assembly, tracks, locus, rebuild: !hasView || scopeChanged || !sameTracks };
}

/** Only the resolved destination config may validate pending track intent. */
export function configuredTrackIds(requested: string[], available: string[], referenceId: string): string[] {
  const known = new Set(available);
  return [...new Set(requested.map((id) => id === "reference_sequence" ? referenceId : id))]
    .filter((id) => known.has(id));
}
