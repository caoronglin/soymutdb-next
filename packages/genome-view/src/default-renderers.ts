import { registerTrackRenderer, resolveTrackRenderer } from "./registry";
import TrackRenderer from "./components/TrackRenderer.vue";
import FeatureTrack from "./components/FeatureTrack.vue";
import QuantitativeTrack from "./components/QuantitativeTrack.vue";
import SequenceTrack from "./components/SequenceTrack.vue";
import VariantTrack from "./components/VariantTrack.vue";

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
  ]) {
    if (!resolveTrackRenderer(type)) {
      registerTrackRenderer(type, { component: TrackRenderer });
    }
  }
}

/** Presentation-only renderers, exported for hosts that fetch records themselves. */
export const trackRenderers = { SequenceTrack, FeatureTrack, VariantTrack, QuantitativeTrack };
