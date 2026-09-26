import { registerTrackRenderer, resolveTrackRenderer } from "./registry";
import FeatureTrack from "./components/FeatureTrack.vue";
import QuantitativeTrack from "./components/QuantitativeTrack.vue";
import SequenceTrack from "./components/SequenceTrack.vue";
import VariantTrack from "./components/VariantTrack.vue";

/**
 * Bind the backend track types to their Vue renderers.
 *
 * Idempotent: a type already registered by the host (or an earlier call) is
 * left alone, so importing this module never throws in a test or a hot reload.
 */
export function registerDefaultTrackRenderers(): void {
  const defaults = {
    ReferenceSequenceTrack: SequenceTrack,
    FeatureTrack,
    VariantTrack,
    QuantitativeTrack,
  } as const;
  for (const [type, component] of Object.entries(defaults)) {
    if (!resolveTrackRenderer(type)) {
      registerTrackRenderer(type, { component });
    }
  }
}
