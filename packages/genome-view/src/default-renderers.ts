import { registerTrackRenderer, resolveTrackRenderer } from "./registry";
import { TrackRenderer } from "./components/TrackRenderer";

/**
 * Bind the backend track types to their React renderers.
 *
 * Each type resolves to the same data-connected `TrackRenderer`, which picks a
 * reader from `@soymutdb/genome-data` and delegates presentation to the matching
 * track view. Idempotent so importing this never throws.
 */
export const DEFAULT_TRACK_TYPES = [
  "ReferenceSequenceTrack",
  "FeatureTrack",
  "VariantTrack",
  "QuantitativeTrack",
  "AlignmentsTrack",
] as const;

export function registerDefaultTrackRenderers(): void {
  for (const type of DEFAULT_TRACK_TYPES) {
    if (!resolveTrackRenderer(type)) {
      registerTrackRenderer(type, { component: TrackRenderer });
    }
  }
}
