import { registerTrackRenderer, resolveTrackRenderer } from "./registry";
import TrackRenderer from "./components/TrackRenderer.vue";

/**
 * Bind the backend track types to their Vue renderers.
 *
 * Each type resolves to the data-connected TrackRenderer, which builds the
 * right reader through @soymutdb/genome-data and delegates presentation to the
 * matching track component. Idempotent so importing this never throws.
 */
export function registerDefaultTrackRenderers(): void {
  for (const type of [
    "ReferenceSequenceTrack",
    "FeatureTrack",
    "VariantTrack",
    "QuantitativeTrack",
    "AlignmentsTrack",
  ]) {
    if (!resolveTrackRenderer(type)) {
      registerTrackRenderer(type, { component: TrackRenderer });
    }
  }
}
