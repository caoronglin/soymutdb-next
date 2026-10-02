/**
 * Interactive genome view.
 *
 * Painting is delegated to the shared SVG renderer so the markup here is exactly
 * what the pre-rendered route emits. Two picture sources:
 *
 * - `prerenderedSrc`: the picture is fetched as a static asset (the server
 *   generated it once), so first paint costs no layout work. A static asset
 *   cannot follow an interaction, so the component switches itself to the live
 *   renderer the moment the user pans or zooms — cheap first paint, correct
 *   behaviour afterwards.
 * - no `prerenderedSrc`: the SVG string is produced in the browser for the
 *   current window from the very first frame.
 *
 * Chrome is deliberately *not* rendered here. This package carries no UI-kit
 * dependency so the portal, the console and the JBrowse shell can each drive it
 * with their own components: the caller passes `renderControls` and receives the
 * resolved window plus the pan/zoom/reset actions.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import type { Region } from "@soymutdb/genome-data";
import { renderGenomeViewSvg, type GenomeViewSvgTheme, type SvgTrack } from "../svg-renderer";
import {
  bpPerPx,
  useGenomeViewport,
  type GenomeViewport,
  type GenomeViewportActions,
} from "../viewport";

/** Everything a caller needs in order to render its own control bar. */
export interface GenomeViewControlsApi {
  /** Current window. */
  viewport: GenomeViewport;
  /** Base pairs per rendered pixel; 0 until the container has been measured. */
  bpPerPx: number;
  /** Rendered width in CSS pixels; 0 until measured. */
  widthPx: number;
  /** Shift the window by `deltaBp`, keeping its span. */
  pan: (deltaBp: number) => void;
  /** Scale the window around `anchorBp` (default: window centre). */
  zoom: (factor: number, anchorBp?: number) => void;
  /** Jump back to the window the component was mounted with. */
  reset: () => void;
  /** A sensible pan distance: one eighth of the current span. */
  panStepBp: number;
  /** True once the user has moved the view away from the pre-rendered window. */
  interacted: boolean;
}

/** Interaction kinds reported through `onAction`. */
export type GenomeViewAction = "pan" | "zoom" | "goto" | "reset" | "drag";

export interface GenomeViewProps {
  /** Initial window; the component owns the window after mount. */
  region: Region;
  /** Feature tracks to draw, already resolved from the backend. */
  tracks: SvgTrack[];
  /** Colours resolved by the caller from the antd theme. */
  theme: GenomeViewSvgTheme;
  /** Static SVG URL for the first paint. See the note at the top. */
  prerenderedSrc?: string;
  /** Accessible label for the whole view. */
  ariaLabel?: string;
  /** Called with the new window after every interaction. */
  onViewportChange?: (viewport: Region) => void;
  /** Notified on every action so the caller can mirror the window in the URL. */
  onAction?: (action: GenomeViewAction) => void;
  /** Renders the caller's own control bar (antd `Button`/`Space`/`Segmented`…). */
  renderControls?: (api: GenomeViewControlsApi) => ReactNode;
  /** Reports the base pair under the pointer, or `null` when it leaves. */
  onHover?: (bp: number | null) => void;
  /** Enables drag-to-pan and wheel-to-zoom. Defaults to true. */
  interactive?: boolean;
  className?: string;
}

/** A floor so the view is never asked to render into zero width. */
const MIN_WIDTH_PX = 320;

/** Wheel zoom step; one notch scales the window by this factor. */
const WHEEL_ZOOM_FACTOR = 1.2;

export function GenomeView({
  region,
  tracks,
  theme,
  prerenderedSrc,
  ariaLabel,
  onViewportChange,
  onAction,
  renderControls,
  onHover,
  interactive = true,
  className,
}: GenomeViewProps) {
  const { viewport, actions } = useGenomeViewport(region);
  const surfaceRef = useRef<HTMLDivElement | null>(null);
  const [widthPx, setWidthPx] = useState(0);
  const [dragging, setDragging] = useState(false);
  const [interacted, setInteracted] = useState(false);

  // Latest values, read from handlers that must not be re-bound on every frame
  // of a drag (re-binding mid-gesture is what drops pointer capture).
  const viewportRef = useRef(viewport);
  viewportRef.current = viewport;
  const widthRef = useRef(widthPx);
  widthRef.current = widthPx;

  const dragRef = useRef<{ startX: number; startBp: number; startEnd: number } | null>(null);
  const frameRef = useRef<number | null>(null);
  const pendingRef = useRef<{ kind: "drag" | "hover"; clientX: number } | null>(null);

  /** A static asset cannot follow an interaction, so it only serves first paint. */
  const usePrerendered = Boolean(prerenderedSrc) && !interacted;

  // Track the container width so the ruler and features stay aligned.
  useEffect(() => {
    const node = surfaceRef.current;
    if (!node) return;
    const measure = () => setWidthPx(Math.max(MIN_WIDTH_PX, node.clientWidth || MIN_WIDTH_PX));
    measure();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", measure);
      return () => window.removeEventListener("resize", measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  useEffect(
    () => () => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    },
    [],
  );

  useEffect(() => {
    onViewportChange?.({
      assemblyKey: viewport.assemblyKey,
      refName: viewport.refName,
      start: viewport.start,
      end: viewport.end,
    });
  }, [viewport, onViewportChange]);

  const markup = useMemo(
    () => (usePrerendered ? null : renderGenomeViewSvg({ viewport, widthPx, tracks, theme })),
    [usePrerendered, viewport, widthPx, tracks, theme],
  );

  const run = useCallback(
    (kind: GenomeViewAction, act: () => void) => {
      setInteracted(true);
      act();
      onAction?.(kind);
    },
    [onAction],
  );

  const zoomAtClientX = useCallback(
    (factor: number, clientX: number | null) => {
      const current = viewportRef.current;
      const width = widthRef.current;
      let anchor: number | undefined;
      if (clientX !== null && surfaceRef.current && width > 0) {
        const rect = surfaceRef.current.getBoundingClientRect();
        const fraction = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
        anchor = current.start + (current.end - current.start) * fraction;
      }
      actions.zoom(factor, anchor);
    },
    [actions],
  );

  /** One rAF per burst of pointer movement: drags stay smooth, React stays calm. */
  const scheduleFrame = useCallback(() => {
    if (frameRef.current !== null) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      const pending = pendingRef.current;
      pendingRef.current = null;
      if (!pending) return;

      const width = widthRef.current;
      const current = viewportRef.current;
      const surface = surfaceRef.current;
      if (!surface || width <= 0) return;

      if (pending.kind === "drag") {
        const drag = dragRef.current;
        if (!drag) return;
        const span = drag.startEnd - drag.startBp;
        const shift = Math.round((-(pending.clientX - drag.startX) * span) / width);
        const nextStart = Math.max(0, drag.startBp + shift);
        actions.gotoLocus(current.refName, nextStart, nextStart + span);
        return;
      }

      if (!onHover) return;
      const rect = surface.getBoundingClientRect();
      if (pending.clientX < rect.left || pending.clientX > rect.right) {
        onHover(null);
        return;
      }
      const fraction = (pending.clientX - rect.left) / rect.width;
      onHover(Math.round(current.start + (current.end - current.start) * fraction));
    });
  }, [actions, onHover]);

  const handlePointerDown = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!interactive || event.button !== 0) return;
      const current = viewportRef.current;
      dragRef.current = {
        startX: event.clientX,
        startBp: current.start,
        startEnd: current.end,
      };
      event.currentTarget.setPointerCapture(event.pointerId);
      setDragging(true);
      setInteracted(true);
    },
    [interactive],
  );

  const handlePointerMove = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!interactive) return;
      pendingRef.current = {
        kind: dragRef.current ? "drag" : "hover",
        clientX: event.clientX,
      };
      scheduleFrame();
    },
    [interactive, scheduleFrame],
  );

  const endDrag = useCallback(
    (event: ReactPointerEvent<HTMLDivElement>) => {
      if (!dragRef.current) return;
      dragRef.current = null;
      setDragging(false);
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      onAction?.("drag");
    },
    [onAction],
  );

  const handlePointerLeave = useCallback(() => {
    if (onHover) onHover(null);
  }, [onHover]);

  // React attaches `wheel` as a passive listener, so `preventDefault` is ignored
  // there; binding it directly on the node is the only way to stop the page from
  // scrolling while the user zooms the track.
  useEffect(() => {
    const node = surfaceRef.current;
    if (!node || !interactive) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.deltaY) return;
      event.preventDefault();
      setInteracted(true);
      zoomAtClientX(event.deltaY > 0 ? WHEEL_ZOOM_FACTOR : 1 / WHEEL_ZOOM_FACTOR, event.clientX);
      onAction?.("zoom");
    };
    node.addEventListener("wheel", onWheel, { passive: false });
    return () => node.removeEventListener("wheel", onWheel);
  }, [interactive, onAction, zoomAtClientX]);

  const scale = bpPerPx(viewport, widthPx);

  const controlsApi = useMemo<GenomeViewControlsApi>(
    () => ({
      viewport,
      bpPerPx: scale,
      widthPx,
      pan: (deltaBp) => run("pan", () => actions.pan(deltaBp)),
      zoom: (factor, anchorBp) => run("zoom", () => actions.zoom(factor, anchorBp)),
      reset: () => run("reset", () => actions.reset(region)),
      panStepBp: Math.max(1, Math.round((viewport.end - viewport.start) / 8)),
      interacted,
    }),
    [viewport, scale, widthPx, run, actions, region, interacted],
  );

  const surfaceStyle: CSSProperties = {
    position: "relative",
    overflowX: usePrerendered ? "hidden" : "auto",
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    cursor: interactive ? (dragging ? "grabbing" : "grab") : "default",
    touchAction: interactive ? "none" : undefined,
    // The markup must not be selectable, or a drag turns into a text selection.
    userSelect: "none",
  };

  return (
    <div className={className}>
      <div
        ref={surfaceRef}
        data-testid="genome-view-surface"
        style={surfaceStyle}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerLeave={handlePointerLeave}
      >
        {usePrerendered ? (
          <img
            src={prerenderedSrc}
            alt={ariaLabel ?? `${viewport.refName}:${viewport.start}-${viewport.end}`}
            draggable={false}
            style={{ display: "block", width: "100%", height: "auto" }}
          />
        ) : (
          <div
            // The markup comes from `renderGenomeViewSvg`, which escapes every
            // interpolated value; no user-supplied string reaches the parser.
            dangerouslySetInnerHTML={{ __html: markup ?? "" }}
            style={{ lineHeight: 0 }}
          />
        )}
      </div>

      {renderControls ? <div>{renderControls(controlsApi)}</div> : null}
    </div>
  );
}

export type { GenomeViewportActions };
