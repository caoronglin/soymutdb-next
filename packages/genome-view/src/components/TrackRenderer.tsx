/**
 * Generic track renderer looked up through the track-type registry.
 *
 * The genome view draws whole tracks through the shared SVG renderer, so this
 * component is the extension point for a track that needs bespoke interactive
 * chrome rather than a lane in that picture. It renders the label and the
 * declared payload, and is what `registerDefaultTrackRenderers` binds each
 * backend track type to.
 */
import type { TrackRendererProps } from "../registry";

export function TrackRenderer({ trackId, label, data }: TrackRendererProps) {
  return (
    <section data-track-id={trackId} aria-label={label}>
      <header style={{ fontSize: 12, opacity: 0.65 }}>{label}</header>
      <pre
        style={{
          margin: 0,
          fontSize: 11,
          maxHeight: 160,
          overflow: "auto",
          whiteSpace: "pre-wrap",
        }}
      >
        {data === undefined ? "No data" : JSON.stringify(data, null, 2)}
      </pre>
    </section>
  );
}
