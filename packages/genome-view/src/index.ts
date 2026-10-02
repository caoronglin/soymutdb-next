/**
 * @soymutdb/genome-view — React genome view.
 *
 * Public surface is deliberately small: the pure geometry, the SVG renderer that
 * both the pre-rendered and interactive paths share, and the React components on
 * top of them.
 */
export {
  bpPerPx,
  bpToPx,
  createViewport,
  gotoViewport,
  MIN_SPAN,
  panViewport,
  useGenomeViewport,
  useStableViewportCallback,
  useViewportKey,
  viewportKey,
  zoomViewport,
  type GenomeViewport,
  type GenomeViewportActions,
} from "./viewport";

export {
  formatBp,
  computeTicks,
  niceStep,
  type RulerRegion,
  type RulerTick,
} from "./ruler";

export {
  clipToRegion,
  layoutIntervals,
  type IntervalLike,
  type LayoutResult,
  type PlacedInterval,
  type RegionLike,
} from "./track-layout";

export {
  mergeExonSpans,
  placeStructureParts,
  type Interval,
  type PlacedPart,
  type StructurePart,
  type StructurePartKind,
} from "./gene-structure";

export {
  genomeViewCacheKey,
  renderGenomeViewSvg,
  type GenomeViewSvgOptions,
  type GenomeViewSvgTheme,
  type SvgFeature,
  type SvgTrack,
} from "./svg-renderer";

export {
  listTrackRenderers,
  registerTrackRenderer,
  resetTrackRenderers,
  resolveTrackRenderer,
  type TrackRendererDescriptor,
  type TrackRendererProps,
} from "./registry";

export { DEFAULT_TRACK_TYPES, registerDefaultTrackRenderers } from "./default-renderers";

export {
  GenomeView,
  type GenomeViewAction,
  type GenomeViewControlsApi,
  type GenomeViewProps,
} from "./components/GenomeView";
export { TrackRenderer } from "./components/TrackRenderer";
