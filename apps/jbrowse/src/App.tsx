import {
    lazy,
    Suspense,
    useCallback,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { observer } from "mobx-react";
import { comparer, reaction } from "mobx";
import {
    createViewState,
    createJBrowseTheme,
    ThemeProvider as JBrowseThemeProvider,
    JBrowseLinearGenomeView,
} from "@jbrowse/react-linear-genome-view";
import { Button, Input, Select, Skeleton } from "@soymutdb/ui-react";
import { http, type AssemblyInfo } from "@soymutdb/api-client";
import { useTranslation } from "react-i18next";
import {
    Maximize2,
    Minimize2,
    Share2,
    Check,
    AlertTriangle,
    Loader2,
    Search,
    ArrowLeft,
} from "lucide-react";
import {
    buildJBrowseConfig,
    buildJBrowseTheme,
    defaultTrackIds,
    type JBrowseAssembly,
    type JBrowseConfig,
    type JBrowseTrack,
} from "./config";
import {
    parseDeepLink,
    buildDeepLink,
    type DeepLinkParams,
} from "./deep-link";
import {
    assembliesRequestParams,
    configRequestParams,
    resolveContextStatus,
    resolveReleaseScope,
} from "./release-context";
import { configuredTrackIds, navigateBrowserView, planPortalInit } from "./bridge-init";
import {
    postToParent,
    parsePortalMessage,
    type InitPayload,
} from "./bridge";

// ---------------------------------------------------------------------------
// Lazy-load the heavy JBrowse React component (code-splitting).
// ---------------------------------------------------------------------------
const LazyJBrowseView = lazy(async () => {
    return { default: JBrowseLinearGenomeView };
});

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** JBrowse config payload returned by the API. */
interface JBrowseConfigResponse {
    assembly?: unknown;
    tracks?: JBrowseTrack[];
}

function isCompleteAssembly(value: unknown): value is JBrowseAssembly {
    if (!value || typeof value !== "object") return false;
    const assembly = value as Partial<JBrowseAssembly>;
    return Boolean(
        typeof assembly.name === "string" &&
            assembly.sequence &&
            typeof assembly.sequence.trackId === "string" &&
            typeof assembly.sequence.type === "string" &&
            assembly.sequence.adapter &&
            typeof assembly.sequence.adapter === "object",
    );
}

/**
 * JBrowse view state — uses `any` for the session because JBrowse's MobX
 * model types are extremely complex and not fully exported.  We access
 * only a small subset of properties at runtime.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type JBrowseViewState = any;

// ---------------------------------------------------------------------------
// Theme hook
// ---------------------------------------------------------------------------

/** Read the active colour theme from the document root. */
function useTheme(): "light" | "dark" {
    const [theme, setTheme] = useState<"light" | "dark">(() => {
        if (typeof document === "undefined") return "light";
        return document.documentElement.getAttribute("data-theme") === "dark"
            ? "dark"
            : "light";
    });

    useEffect(() => {
        const observer = new MutationObserver(() => {
            setTheme(
                document.documentElement.getAttribute("data-theme") === "dark"
                    ? "dark"
                    : "light",
            );
        });
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ["data-theme"],
        });
        return () => observer.disconnect();
    }, []);

    return theme;
}

// ---------------------------------------------------------------------------
// Main App component
// ---------------------------------------------------------------------------

function JBrowseApp() {
    const { t } = useTranslation();
    const theme = useTheme();

    // Parse initial deep-link params from the URL.
    const initialParams = useMemo<DeepLinkParams>(() => {
        if (typeof window === "undefined") return {};
        return parseDeepLink(window.location.search);
    }, []);

    // Embedded mode: the portal appends ?portalOrigin=<origin> when loading us
    // in an iframe. Without it we stay fully standalone (default behaviour).
    const isEmbedded = Boolean(initialParams.portalOrigin);
    const parentOrigin =
        initialParams.portalOrigin ?? (typeof window !== "undefined" ? window.location.origin : "*");

    const [currentLocus, setCurrentLocus] = useState<string | undefined>(
        initialParams.locus,
    );
    const [activeTracks, setActiveTracks] = useState<string[] | undefined>(initialParams.tracks);
    const [assemblyName, setAssemblyName] = useState<string>(
        initialParams.assembly ?? "",
    );
    const [release, setRelease] = useState<string | undefined>(initialParams.release);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [shareCopied, setShareCopied] = useState(false);
    const [locusInput, setLocusInput] = useState(initialParams.locus ?? "");
    const [viewState, setViewState] = useState<JBrowseViewState | null>(null);
    const [initError, setInitError] = useState<string | null>(null);
    const [navigationError, setNavigationError] = useState(false);
    // Bumped by applyInit() when an init message must rebuild the view state
    // (assembly/tracks changes). Locus-only updates navigate instead.
    const [sessionNonce, setSessionNonce] = useState(0);
    const containerRef = useRef<HTMLDivElement>(null);

    const readySentViewRef = useRef<JBrowseViewState | null>(null);
    const locusDebounceRef = useRef<number | null>(null);
    // Monotonic scope tag handed out by the portal; stale scopes are ignored.
    const scopeEpochRef = useRef<number | undefined>(undefined);

    // Resolve the deep link to the canonical assembly identity of a published
    // release.
    //
    // The API deliberately rejects name-only track lookups: the same assembly
    // name can exist in several releases with different tracks, so a release's
    // numeric assembly id is the only stable identity. The *release* itself is
    // not hardcoded here — with no `release` in the deep link the server
    // resolves the active published release, which is an unambiguous
    // server-authoritative answer. The assembly, however, is never guessed by
    // name: an unknown name is an error, and an absent name adopts the
    // release's declared default assembly.
    //
    // The release is pinned *explicitly* on both requests below (an explicit
    // `release_id` parameter, never a process-wide release pin): the assembly
    // list and the track configuration must be read from the same release, or
    // the assembly id resolved from one request names a coordinate namespace
    // the other request does not serve.
    const releaseScope = useMemo(() => resolveReleaseScope(release), [release]);
    // An unusable release gets its own cache slot: it must never reuse the
    // cached "active" assembly list, and it must not send a request at all.
    const releaseCacheKey = releaseScope.invalid
        ? "invalid-release"
        : (releaseScope.releaseId ?? "active");

    const {
        data: assemblies,
        isLoading: assembliesLoading,
        isError: assembliesIsError,
    } = useQuery<AssemblyInfo[]>({
        queryKey: ["jbrowse-assemblies", releaseCacheKey],
        queryFn: () =>
            http.get<AssemblyInfo[]>("/genes/assemblies", {
                params: assembliesRequestParams(releaseScope),
            }),
        enabled: !releaseScope.invalid,
        retry: false,
        staleTime: 5 * 60 * 1000,
    });

    // Adopt the release's default assembly when the deep link did not name one.
    // This is a server-declared identity, not a v4/v5 substitution.
    useEffect(() => {
        if (assemblyName || !assemblies || assemblies.length === 0) return;
        const preferred = assemblies.find((item) => item.is_default) ?? assemblies[0];
        if (preferred?.name) setAssemblyName(preferred.name);
    }, [assemblies, assemblyName]);

    const resolvedAssembly = useMemo(() => {
        if (!assemblies || !assemblyName) return undefined;
        return (
            assemblies.find((item) => item.name === assemblyName) ??
            assemblies.find((item) => item.id != null && String(item.id) === assemblyName)
        );
    }, [assemblies, assemblyName]);

    const assemblyId = resolvedAssembly?.id;
    // A named-but-unknown assembly is a hard error; the API unavailable is also
    // an error because we cannot prove the assembly belongs to the release.
    const assemblyContextError =
        assembliesIsError || (assemblies != null && assemblyName !== "" && !resolvedAssembly);

    // The configuration request carries the assembly id *and* the release of
    // the same scope, so the two can never disagree.
    const configParams = useMemo(
        () => (assemblyId == null ? null : configRequestParams(releaseScope, assemblyId)),
        [assemblyId, releaseScope],
    );

    // Fetch the complete, release-scoped JBrowse config from the API. A name-only
    // response or an unavailable request is not safe to turn into a v4 fallback.
    const {
        data: configData,
        isLoading: configLoading,
        isError: configIsError,
    } = useQuery<JBrowseConfigResponse>({
        queryKey: ["jbrowse-config", assemblyId, releaseCacheKey],
        queryFn: () =>
            http.get<JBrowseConfigResponse>("/tracks/jbrowse-config", {
                params: configParams ?? undefined,
            }),
        enabled: configParams != null && !releaseScope.invalid,
        retry: false,
        staleTime: 5 * 60 * 1000,
    });

    const config: JBrowseConfig | null = useMemo(() => {
        if (!resolvedAssembly || !configData || !isCompleteAssembly(configData.assembly)
            || configData.assembly.name !== resolvedAssembly.name) return null;
        return buildJBrowseConfig(configData.assembly, configData.tracks ?? []);
    }, [configData, resolvedAssembly]);

    // JBrowse theme matching the SoyMutDB green scientific theme.
    const jbrowseTheme = useMemo(
        () => createJBrowseTheme(buildJBrowseTheme(theme)),
        [theme],
    );

    // Latest state snapshot for stable bridge callbacks (avoids stale closures).
    const stateRef = useRef({
        release,
        assembly: assemblyName,
        tracks: activeTracks,
        locus: currentLocus,
        view: viewState as JBrowseViewState | null,
        config,
    });
    useEffect(() => {
        stateRef.current = {
            release,
            assembly: assemblyName,
            tracks: activeTracks,
            locus: currentLocus,
            view: viewState,
            config,
        };
    }, [activeTracks, assemblyName, config, currentLocus, release, viewState]);

    // Safe track types supported by @jbrowse/react-linear-genome-view corePlugins.
    // This is a runtime safety net complementing validateTrackTypes() in config.ts.
    const SAFE_TRACK_TYPES = new Set([
        "ReferenceSequenceTrack",
        "VariantTrack",
        "FeatureTrack",
        "QuantitativeTrack",
        "AlignmentsTrack",
    ]);

    // Filter tracks to only include types JBrowse corePlugins can handle.
    // Tracks with unknown types are converted to FeatureTrack to avoid the
    // "TrackType 'undefined' not found" runtime error.
    const safeTracks = (config?.tracks ?? []).map((track) => {
        if (SAFE_TRACK_TYPES.has(track.type)) return track;
        console.warn(
            `[JBrowse] Track "${track.trackId}" has unsupported type "${track.type}", falling back to FeatureTrack`,
        );
        return { ...track, type: "FeatureTrack" };
    });

    // A release switch invalidates the session: the assembly id behind the
    // current view belongs to the previous release's coordinate namespace, and
    // the previous release's tracks must never stay on screen under the new
    // one. The view is dropped here and rebuilt from the new release's own
    // assembly list (and its own configuration) by the effect below.
    //
    // Declared *before* the view-state effect so that the reason for the
    // missing view is computed after this reset, not before it.
    const previousReleaseRef = useRef<string | undefined>(release);
    useEffect(() => {
        if (previousReleaseRef.current === release) return;
        previousReleaseRef.current = release;
        setViewState(null);
        setInitError(null);
    }, [release]);

    // Initialise only from the resolved release's complete configuration.
    // Pending intent survives loading; no default/previous-release fallback.
    //
    // createViewState expects:
    //   assembly:  assembly config OBJECT (not a name string)
    //   tracks:    track config OBJECTS array (not track ID strings)
    //   configuration: extra config (theme is handled by JBrowseThemeProvider)
    //   defaultSession: session with view tracks referencing config track IDs
    //
    // All required plugins (Variants, Alignments, Wiggle, GFF3, Sequence,
    // etc.) are pre-bundled in @jbrowse/react-linear-genome-view corePlugins
    // and registered automatically by createModel().
    useEffect(() => {
        if (!config) {
            setViewState(null);
            if (configLoading || assembliesLoading || (!assemblyName && assemblies?.length)) {
                setInitError(null);
            } else {
                const { message } = resolveContextStatus({
                    releaseInvalid: releaseScope.invalid,
                    assembly: assemblyName,
                    assembliesError: assembliesIsError,
                    assemblyFound: Boolean(resolvedAssembly),
                    configError: configIsError,
                });
                setInitError(message || null);
            }
            return;
        }
        const frame = requestAnimationFrame(() => {
            try {
                const assemblyConfig = config.assemblies[0];
                if (!assemblyConfig) throw new Error("The JBrowse configuration has no reference assembly.");
                const requestedTracks = activeTracks
                    ?? defaultTrackIds(safeTracks, assemblyConfig.sequence.trackId);
                const resolvedTracks = configuredTrackIds(
                    requestedTracks,
                    safeTracks.map((track) => track.trackId), assemblyConfig.sequence.trackId,
                );
                // Never open an empty browser: a selection that does not exist
                // in the destination release falls back to that release's own
                // defaults instead of showing a reference-less viewport.
                const sessionTracks = resolvedTracks.length
                    ? resolvedTracks
                    : defaultTrackIds(safeTracks, assemblyConfig.sequence.trackId);
                setActiveTracks(sessionTracks);
                const state = createViewState({
                    assembly: assemblyConfig,
                    tracks: safeTracks,
                    aggregateTextSearchAdapters: config.aggregateTextSearchAdapters,
                    location: currentLocus,
                    configuration: {},
                    defaultSession: {
                        name: "SoyMutDB",
                        view: {
                            id: "linear_genome_view",
                            type: "LinearGenomeView",
                            bpPerPx: 200,
                            tracks: sessionTracks.map((actualId) => {
                                const track = safeTracks.find((t) => t.trackId === actualId);
                                return {
                                    id: actualId,
                                    type: track?.type ?? "FeatureTrack",
                                    displays: [],
                                };
                            }),
                        },
                    },
                }) as JBrowseViewState;
                setViewState(state);
                setInitError(null);
            } catch (err) {
                setInitError(
                    err instanceof Error ? err.message : "Failed to initialise genome browser",
                );
            }
        });
        return () => cancelAnimationFrame(frame);
        // Only re-init when the assembly changes (or the bridge asks for a
        // full re-init via sessionNonce). activeTracks/currentLocus/safeTracks
        // are read from stateRef by the bridge effects on purpose: making them
        // dependencies would tear down and rebuild the JBrowse view on every
        // pan or track toggle.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        assemblyContextError,
        assemblyName,
        assembliesIsError,
        assembliesLoading,
        config,
        configIsError,
        configLoading,
        release,
        releaseScope,
        resolvedAssembly,
        sessionNonce,
    ]);

    // -----------------------------------------------------------------------
    // postMessage bridge with the embedding portal
    // -----------------------------------------------------------------------

    // Apply an `init` message from the portal: assembly/tracks changes rebuild
    // the view state (sessionNonce), locus-only changes navigate in place.
    const applyInit = useCallback((payload: InitPayload | undefined) => {
        if (!payload || typeof payload !== "object") return;
        const s = stateRef.current;

        // The portal tags every scope with a monotonic epoch. An init message
        // from an older scope must never revive coordinates or tracks that
        // belong to a release the user already left.
        const incomingEpoch = typeof payload.scopeEpoch === "number" ? payload.scopeEpoch : undefined;
        if (incomingEpoch != null && scopeEpochRef.current != null
            && incomingEpoch < scopeEpochRef.current) return;
        if (incomingEpoch != null) scopeEpochRef.current = incomingEpoch;

        const next = planPortalInit(s, payload, Boolean(s.view));
        // Store intent even before any config exists. Never filter destination
        // tracks against a previous release's config or navigate its old view.
        stateRef.current = { ...s, ...next, locus: next.rebuild ? next.locus : s.locus, view: next.rebuild ? null : s.view };
        setRelease(next.release);
        setAssemblyName(next.assembly);
        setActiveTracks(next.tracks);
        setLocusInput(next.locus ?? "");
        setNavigationError(false);
        if (next.rebuild) {
            setCurrentLocus(next.locus);
            setViewState(null);
            setInitError(null);
            setSessionNonce((n) => n + 1);
            return;
        }
        if (next.locus && next.locus !== s.locus) {
            const view = s.view?.session?.views?.[0];
            if (view) void navigateBrowserView(view, next.locus, s.config?.assemblies[0]?.name, s.view.session.assemblyManager)
                .then((locus) => {
                    if (locus && stateRef.current.view === s.view) setCurrentLocus(locus);
                })
                .catch(() => { if (stateRef.current.view === s.view) setNavigationError(true); });
        }
    }, []);

    // Listen for `init` messages from the portal. Active only when embedded.
    useEffect(() => {
        if (!isEmbedded) return;
        const handleMessage = (event: MessageEvent) => {
            const msg = parsePortalMessage(event, parentOrigin);
            if (!msg) return; // already warned inside the validator
            if (msg.type === "init") {
                applyInit(msg.payload as InitPayload | undefined);
            } else if (msg.type === "selection-change") {
                // Optional — reserved for future use; nothing to do.
            } else {
                console.warn(`[JBrowse] Ignoring unexpected bridge message type: ${String(msg.type)}`);
            }
        };
        window.addEventListener("message", handleMessage);
        return () => window.removeEventListener("message", handleMessage);
    }, [isEmbedded, parentOrigin, applyInit]);

    // Announce readiness (or failure) to the portal.
    useEffect(() => {
        if (!isEmbedded) return;
        if (initError) {
            postToParent({ type: "error", payload: { message: initError } }, parentOrigin);
            return;
        }
        if (viewState && readySentViewRef.current !== viewState) {
            readySentViewRef.current = viewState;
            // `stateRef` holds the live assembly/locus snapshot. Reading it
            // here (instead of closing over the state values) keeps the ready
            // message accurate without re-firing on every pan.
            const live = stateRef.current;
            postToParent(
                { type: "ready", payload: { assembly: live.assembly, locus: live.locus } },
                parentOrigin,
            );
        }
    }, [viewState, initError, isEmbedded, parentOrigin]);

    // Notify the portal about viewport changes (debounced 300ms).
    useEffect(() => {
        if (!isEmbedded || !currentLocus) return;
        if (!stateRef.current.view) return; // wait until the view actually exists
        if (locusDebounceRef.current !== null) {
            window.clearTimeout(locusDebounceRef.current);
        }
        locusDebounceRef.current = window.setTimeout(() => {
            const s = stateRef.current;
            if (!s.view || !s.locus) return;
            postToParent(
                {
                    type: "locus-change",
                    payload: {
                        assembly: s.assembly,
                        locus: s.locus,
                        tracks: s.tracks,
                        release: s.release,
                        scopeEpoch: scopeEpochRef.current,
                    },
                },
                parentOrigin,
            );
        }, 300);
        return () => {
            if (locusDebounceRef.current !== null) {
                window.clearTimeout(locusDebounceRef.current);
                locusDebounceRef.current = null;
            }
        };
    }, [currentLocus, activeTracks, assemblyName, release, viewState, isEmbedded, parentOrigin]);

    // Subscribe to view changes to keep URL and state in sync.
    useEffect(() => {
        if (!viewState?.session) return;
        const session = viewState.session;
        const view = session.views?.[0];
        if (!view) return;

        // JBrowse exposes a MobX model, not subscribeToViewState(). Observe
        // its real viewport/track properties and dispose with this view.
        return reaction(
            () => ({
                locus: view.visibleLocStrings as string | undefined,
                tracks: (view.tracks ?? [])
                    .map((track: { configuration?: { trackId?: string } }) => track.configuration?.trackId)
                    .filter((id: unknown): id is string => typeof id === "string"),
            }),
            ({ locus, tracks }) => {
                if (stateRef.current.view !== viewState) return;
                if (locus && locus !== stateRef.current.locus) {
                    setCurrentLocus(locus);
                    setLocusInput(locus);
                }
                setActiveTracks(tracks);
            },
            { equals: comparer.structural, fireImmediately: true },
        );
    }, [viewState]);

    // Update the URL when locus, tracks, assembly or release change
    // (replaceState to avoid history spam).
    useEffect(() => {
        if (typeof window === "undefined") return;
        const url = buildDeepLink({
            locus: currentLocus,
            tracks: activeTracks,
            assembly: assemblyName,
            release,
        });
        window.history.replaceState(null, "", url);
    }, [currentLocus, activeTracks, assemblyName, release]);

    // Fullscreen toggle.
    const toggleFullscreen = useCallback(async () => {
        if (!containerRef.current) return;
        try {
            if (!document.fullscreenElement) {
                await containerRef.current.requestFullscreen();
                setIsFullscreen(true);
            } else {
                await document.exitFullscreen();
                setIsFullscreen(false);
            }
        } catch {
            // Fullscreen may be blocked; fail silently.
        }
    }, []);

    useEffect(() => {
        const handler = () => setIsFullscreen(Boolean(document.fullscreenElement));
        document.addEventListener("fullscreenchange", handler);
        return () => document.removeEventListener("fullscreenchange", handler);
    }, []);

    // Share link generation.
    const handleShare = useCallback(async () => {
        const url = buildDeepLink({
            locus: currentLocus,
            tracks: activeTracks,
            assembly: assemblyName,
            release,
        });
        try {
            await navigator.clipboard.writeText(url);
            setShareCopied(true);
            setTimeout(() => setShareCopied(false), 2000);
        } catch {
            // Fallback: select the URL in the address bar.
            window.prompt("Copy this link to share:", url);
        }
    }, [currentLocus, activeTracks, assemblyName, release]);

    // Navigate to a typed locus.
    const handleNavigate = useCallback(
        (e: React.FormEvent) => {
            e.preventDefault();
            const trimmed = locusInput.trim();
            if (!trimmed) return;
            const view = viewState?.session?.views?.[0];
            if (!view) return;
            setNavigationError(false);
            void navigateBrowserView(view, trimmed, config?.assemblies[0]?.name, viewState.session.assemblyManager)
                .then((locus) => {
                    if (locus && stateRef.current.view === viewState) setCurrentLocus(locus);
                })
                .catch(() => { if (stateRef.current.view === viewState) setNavigationError(true); });
        },
        [config, locusInput, viewState],
    );

    const isLoading = !viewState && !initError;

    return (
        <div className="flex min-h-screen flex-col bg-background text-foreground">
            {/* Header bar — wraps into two rows on narrow screens so the back
                button, locus input and track actions stay usable. */}
            <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2">
                    {isEmbedded && (
                        <Button
                            type="text"
                            size="small"
                            href={parentOrigin}
                            target="_top"
                            rel="noopener noreferrer"
                            icon={<ArrowLeft className="size-4" aria-hidden />}
                            className="-ml-2 shrink-0"
                            aria-label={t("browser.backToPortal")}
                            title={t("browser.backToPortal")}
                        >
                            <span className="hidden md:inline">{t("browser.backToPortal")}</span>
                        </Button>
                    )}

                    <div className="flex items-center gap-2">
                        <span className="font-serif text-lg font-semibold text-primary">
                            SoyMutDB
                        </span>
                        <span className="hidden text-sm text-muted-foreground sm:inline">
                            Genome Browser
                        </span>
                    </div>

                    {/* Assembly selector.
                        Options come from the selected published release's own
                        assembly list — never a hardcoded trio. A name the
                        release does not contain would otherwise be selectable
                        and then fail (or worse, be substituted) at config
                        time. */}
                    <Select
                        value={assemblyName || undefined}
                        onChange={(assembly: string) => applyInit({ assembly })}
                        className="w-44 shrink-0 font-mono"
                        aria-label="Select reference assembly"
                        loading={assembliesLoading}
                        disabled={assembliesIsError || (assemblies?.length ?? 0) === 0}
                        placeholder={assembliesLoading ? "Loading…" : "Select assembly"}
                        options={(assemblies ?? []).map((item) => ({
                            value: item.name,
                            label: item.version ? `${item.name} (${item.version})` : item.name,
                        }))}
                    />

                    <form
                        onSubmit={handleNavigate}
                        className="flex min-w-0 flex-1 basis-full items-center gap-2 sm:ml-auto sm:basis-auto"
                    >
                        <div className="relative min-w-0 flex-1">
                            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                            <Input
                                type="text"
                                value={locusInput}
                                onChange={(e) => setLocusInput(e.target.value)}
                                placeholder="chr01:1-1000000 or gene ID"
                                className="h-9 w-full min-w-0 pl-8 font-mono text-sm"
                                aria-label="Genomic location or gene search"
                            />
                        </div>
                        <Button htmlType="submit" type="primary" size="small" disabled={!viewState || Boolean(initError)} className="shrink-0">
                            Go
                        </Button>
                    </form>
                    {navigationError && <p role="alert" className="basis-full text-sm text-destructive">{t("browser.navigationError")}</p>}

                    <div className="ml-auto flex shrink-0 items-center gap-1 sm:ml-0">
                        <Button
                            type="text"
                            onClick={handleShare}
                            aria-label="Share current view"
                            title="Share this view"
                            icon={shareCopied ? (
                                <Check className="size-4 text-primary" />
                            ) : (
                                <Share2 className="size-4" />
                            )}
                        >
                        </Button>
                        <Button
                            type="text"
                            onClick={toggleFullscreen}
                            aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
                            title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
                            icon={isFullscreen ? (
                                <Minimize2 className="size-4" />
                            ) : (
                                <Maximize2 className="size-4" />
                            )}
                        >
                        </Button>
                    </div>
                </div>

                {/* Active tracks / locus summary bar */}
                <div className="flex items-center gap-3 border-t border-border bg-muted/30 px-4 py-1.5 text-xs text-muted-foreground">
                    <span className="font-mono">
                        {currentLocus ?? "No location selected"}
                    </span>
                    <span className="text-border">·</span>
                    <span>
                        {activeTracks?.length ?? 0} active track{activeTracks?.length === 1 ? "" : "s"}
                    </span>
                    <span className="text-border">·</span>
                    <span>Assembly: {assemblyName}</span>
                </div>
            </header>

            {/* JBrowse view container */}
            <main
                ref={containerRef}
                data-testid="jbrowse-view"
                data-view-ready={viewState && !initError ? "true" : "false"}
                className={`jbrowse-container relative flex-1 overflow-hidden bg-background${
                    isFullscreen ? " fixed inset-0 z-50" : ""
                }`}
            >
                {isLoading && <LoadingPlaceholder />}
                {initError && (
                    <ErrorPlaceholder
                        message={initError}
                        onRetry={() => window.location.reload()}
                    />
                )}
                {viewState && !initError && (
                    <JBrowseThemeProvider _theme={jbrowseTheme}>
                        <Suspense fallback={<LoadingPlaceholder />}>
                            <div className="jbrowse-fade-in h-full w-full">
                                <LazyJBrowseView viewState={viewState} />
                            </div>
                        </Suspense>
                    </JBrowseThemeProvider>
                )}
            </main>

            {/* Footer */}
            <footer className="border-t border-border bg-card px-4 py-2 text-center text-xs text-muted-foreground">
                Powered by JBrowse 2 · SoyMutDB Genome Browser ·{" "}
                {(activeTracks?.length ?? 0) > 0 && (
                    <span>{activeTracks?.length.toLocaleString()} tracks loaded</span>
                )}
            </footer>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Placeholder components
// ---------------------------------------------------------------------------

function LoadingPlaceholder() {
    const { t } = useTranslation();
    return (
        <div
            data-testid="jbrowse-loading"
            className="flex h-full w-full flex-col items-center justify-center gap-4 bg-muted/20 p-8"
            role="status"
            aria-live="polite"
        >
            <Loader2 className="size-8 animate-spin text-primary" aria-hidden />
            <Skeleton.Node active className="h-64! w-full! max-w-3xl! rounded-lg!" />
            <p className="text-sm text-muted-foreground">
                {t("browser.loading")}
            </p>
        </div>
    );
}

interface ErrorPlaceholderProps {
    message: string;
    onRetry: () => void;
}

function ErrorPlaceholder({ message, onRetry }: ErrorPlaceholderProps) {
    return (
        <div
            data-testid="jbrowse-unavailable"
            className="flex h-full w-full flex-col items-center justify-center gap-4 bg-muted/20 p-8 text-center"
            role="alert"
        >
            <div className="flex size-12 items-center justify-center rounded-full bg-destructive/10">
                <AlertTriangle className="size-6 text-destructive" aria-hidden />
            </div>
            <div>
                <h2 className="font-serif text-lg font-semibold">
                    Unable to load genome browser
                </h2>
                <p className="mt-1 max-w-md text-sm text-muted-foreground">{message}</p>
            </div>
            <Button size="small" onClick={onRetry}>
                Retry
            </Button>
        </div>
    );
}

export default observer(JBrowseApp);
