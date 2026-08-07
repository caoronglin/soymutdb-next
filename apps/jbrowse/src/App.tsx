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
import {
    createViewState,
    createJBrowseTheme,
    ThemeProvider as JBrowseThemeProvider,
    JBrowseLinearGenomeView,
} from "@jbrowse/react-linear-genome-view";
import { Button, Skeleton, Input } from "@soymutdb/ui";
import { cn, formatNumber } from "@soymutdb/ui";
import { http } from "@soymutdb/api-client";
import {
    Maximize2,
    Minimize2,
    Share2,
    Check,
    AlertTriangle,
    Loader2,
    Search,
} from "lucide-react";
import {
    buildJBrowseConfig,
    buildJBrowseTheme,
    buildAssembly,
    DEFAULT_ASSEMBLY,
    DEFAULT_TRACKS,
    ALL_TRACKS,
    type JBrowseConfig,
    type JBrowseTrack,
} from "./config";
import {
    parseDeepLink,
    buildDeepLink,
    parseLocus,
    formatLocus,
    type DeepLinkParams,
} from "./deep-link";

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
    assembly: typeof DEFAULT_ASSEMBLY;
    tracks: JBrowseTrack[];
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
    const theme = useTheme();

    // Parse initial deep-link params from the URL.
    const initialParams = useMemo<DeepLinkParams>(() => {
        if (typeof window === "undefined") return {};
        return parseDeepLink(window.location.search);
    }, []);

    const [currentLocus, setCurrentLocus] = useState<string | undefined>(
        initialParams.locus,
    );
    const [activeTracks, setActiveTracks] = useState<string[]>(
        initialParams.tracks ?? DEFAULT_TRACKS,
    );
    const [assemblyName, setAssemblyName] = useState<string>(
        initialParams.assembly ?? DEFAULT_ASSEMBLY.name,
    );
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [shareCopied, setShareCopied] = useState(false);
    const [locusInput, setLocusInput] = useState(initialParams.locus ?? "");
    const [viewState, setViewState] = useState<JBrowseViewState | null>(null);
    const [initError, setInitError] = useState<string | null>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    // Fetch JBrowse config from the API.
    // When the backend is unavailable, we fall back to the built-in default
    // config (DEFAULT_ASSEMBLY + ALL_TRACKS) so the genome browser still works.
    const { data: configData } =
        useQuery<JBrowseConfigResponse>({
            queryKey: ["jbrowse-config", assemblyName],
            queryFn: () =>
                http.get<JBrowseConfigResponse>("/tracks/jbrowse-config", {
                    params: { assembly: assemblyName },
                }),
            retry: false,
            staleTime: 5 * 60 * 1000,
        });

    // Build the JBrowse configuration — fall back to defaults on API failure.
    const config: JBrowseConfig = useMemo(() => {
        // When API is unavailable, build an assembly config matching the
        // selected name so the browser and dropdown stay in sync.
        const assembly = configData?.assembly ?? buildAssembly(assemblyName);
        // Use ALL_TRACKS as fallback so the browser has tracks even without API.
        const tracks = configData?.tracks ?? ALL_TRACKS;
        return buildJBrowseConfig(assembly, tracks);
    }, [configData, assemblyName]);

    // JBrowse theme matching the SoyMutDB green scientific theme.
    const jbrowseTheme = useMemo(
        () => createJBrowseTheme(buildJBrowseTheme(theme)),
        [theme],
    );

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
    const safeTracks = config.tracks.map((track) => {
        if (SAFE_TRACK_TYPES.has(track.type)) return track;
        console.warn(
            `[JBrowse] Track "${track.trackId}" has unsupported type "${track.type}", falling back to FeatureTrack`,
        );
        return { ...track, type: "FeatureTrack" };
    });

    // Initialise the JBrowse view state when config is ready.
    // We don't block on configLoading — if the API is slow or unavailable,
    // the default config is used immediately.
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
        try {
            const assemblyConfig = config.assemblies[0] ?? DEFAULT_ASSEMBLY;
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
                        tracks: activeTracks.map((id) => {
                            // Map "reference_sequence" to the assembly's actual trackId.
                            const actualId =
                                id === "reference_sequence"
                                    ? assemblyConfig.sequence.trackId
                                    : id;
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
        // Only re-init when the assembly changes; track/locus updates are handled below.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [config, assemblyName]);

    // Subscribe to view changes to keep URL and state in sync.
    useEffect(() => {
        if (!viewState?.session) return;
        const session = viewState.session;
        const view = session.views?.[0];
        if (!view) return;

        const dispose = view.subscribeToViewState?.(() => {
            const visibleLoc = view.visibleLocString;
            if (visibleLoc && visibleLoc !== currentLocus) {
                setCurrentLocus(visibleLoc);
                setLocusInput(visibleLoc);
            }
            const tracks = (view.tracks ?? [])
                .map((t: { configuration?: { trackId?: string } }) => t.configuration?.trackId)
                .filter((id: unknown): id is string => typeof id === "string");
            if (tracks.length > 0) {
                setActiveTracks(tracks);
            }
        });

        return () => {
            dispose?.();
        };
    }, [viewState, currentLocus]);

    // Update the URL when locus or tracks change (replaceState to avoid history spam).
    useEffect(() => {
        if (typeof window === "undefined") return;
        const url = buildDeepLink({
            locus: currentLocus,
            tracks: activeTracks,
            assembly: assemblyName,
        });
        window.history.replaceState(null, "", url);
    }, [currentLocus, activeTracks, assemblyName]);

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
        });
        try {
            await navigator.clipboard.writeText(url);
            setShareCopied(true);
            setTimeout(() => setShareCopied(false), 2000);
        } catch {
            // Fallback: select the URL in the address bar.
            window.prompt("Copy this link to share:", url);
        }
    }, [currentLocus, activeTracks, assemblyName]);

    // Navigate to a typed locus.
    const handleNavigate = useCallback(
        (e: React.FormEvent) => {
            e.preventDefault();
            const trimmed = locusInput.trim();
            if (!trimmed) return;
            const parsed = parseLocus(trimmed);
            if (!parsed) {
                // Treat as a gene/feature search — JBrowse will handle via text search.
                viewState?.session?.views?.[0]?.navToSearchResults?.({ input: trimmed });
                return;
            }
            viewState?.session?.views?.[0]?.navTo?.({
                refName: parsed.refName,
                start: parsed.start,
                end: parsed.end,
            });
            setCurrentLocus(formatLocus(parsed));
        },
        [locusInput, viewState],
    );

    const isLoading = !viewState && !initError;

    return (
        <div className="flex min-h-screen flex-col bg-background text-foreground">
            {/* Header bar */}
            <header className="sticky top-0 z-30 border-b border-border bg-card/95 backdrop-blur supports-[backdrop-filter]:bg-card/80">
                <div className="flex h-14 items-center gap-3 px-4">
                    <div className="flex items-center gap-2">
                        <span className="font-serif text-lg font-semibold text-primary">
                            SoyMutDB
                        </span>
                        <span className="hidden text-sm text-muted-foreground sm:inline">
                            Genome Browser
                        </span>
                    </div>

                    {/* Assembly selector */}
                    <select
                        value={assemblyName}
                        onChange={(e) => setAssemblyName(e.target.value)}
                        className="h-9 rounded-md border border-border bg-card px-3 text-sm font-mono text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                        aria-label="Select reference assembly"
                    >
                        <option value="Wm82v4.0">Wm82 v4.0</option>
                        <option value="Wm82.a4.v1">Wm82.a4.v1</option>
                        <option value="Wm82.a2.v1">Wm82.a2.v1</option>
                    </select>

                    <form onSubmit={handleNavigate} className="ml-auto flex items-center gap-2">
                        <div className="relative">
                            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                            <Input
                                type="text"
                                value={locusInput}
                                onChange={(e) => setLocusInput(e.target.value)}
                                placeholder="chr01:1-1000000 or gene ID"
                                className="h-9 w-56 pl-8 font-mono text-sm md:w-80"
                                aria-label="Genomic location or gene search"
                            />
                        </div>
                        <Button type="submit" size="sm" variant="default">
                            Go
                        </Button>
                    </form>

                    <div className="flex items-center gap-1">
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={handleShare}
                            aria-label="Share current view"
                            title="Share this view"
                        >
                            {shareCopied ? (
                                <Check className="size-4 text-primary" />
                            ) : (
                                <Share2 className="size-4" />
                            )}
                        </Button>
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={toggleFullscreen}
                            aria-label={isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
                            title={isFullscreen ? "Exit fullscreen" : "Fullscreen"}
                        >
                            {isFullscreen ? (
                                <Minimize2 className="size-4" />
                            ) : (
                                <Maximize2 className="size-4" />
                            )}
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
                        {activeTracks.length} active track{activeTracks.length === 1 ? "" : "s"}
                    </span>
                    <span className="text-border">·</span>
                    <span>Assembly: {assemblyName}</span>
                </div>
            </header>

            {/* JBrowse view container */}
            <main
                ref={containerRef}
                className={cn(
                    "jbrowse-container relative flex-1 overflow-hidden bg-background",
                    isFullscreen && "fixed inset-0 z-50",
                )}
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
                {activeTracks.length > 0 && (
                    <span>{formatNumber(activeTracks.length)} tracks loaded</span>
                )}
            </footer>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Placeholder components
// ---------------------------------------------------------------------------

function LoadingPlaceholder() {
    return (
        <div
            className="flex h-full w-full flex-col items-center justify-center gap-4 bg-muted/20 p-8"
            role="status"
            aria-live="polite"
        >
            <Loader2 className="size-8 animate-spin text-primary" aria-hidden />
            <Skeleton className="h-64 w-full max-w-3xl rounded-lg" />
            <p className="text-sm text-muted-foreground">
                Loading genome browser…
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
            <Button variant="outline" size="sm" onClick={onRetry}>
                Retry
            </Button>
        </div>
    );
}

export default observer(JBrowseApp);
