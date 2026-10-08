/**
 * Genome browser route — JBrowse 2 embed with a postMessage bridge.
 *
 * JBrowse 2 is loaded via an iframe. The URL is configurable via the
 * VITE_JBROWSE_URL env var (defaults to the local JBrowse app).
 *
 * Reliability model (replaces the old onLoad + 8s heuristic):
 *   - The iframe is considered ready ONLY when it posts a `ready` bridge
 *     message (contract in ../lib/jbrowse-bridge).
 *   - If no `ready` arrives within 15s, a "still loading / retry" panel is
 *     shown; success is never inferred from timers or iframe load events.
 *   - After `ready`, the portal sends an `init` message carrying the
 *     deep-link state (assembly/locus/tracks/release) restored from the URL.
 *   - Locus changes inside JBrowse (`locus-change`) update the URL with
 *     router `replace` semantics; URL-driven changes are pushed back via
 *     `init` without reloading the iframe.
 *   - Incoming messages are validated against origin + source + version
 *     (+ iframe contentWindow identity); anything invalid is ignored with a
 *     console warning.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import * as React from "react";
import {
  AimOutlined as Microscope,
  ArrowLeftOutlined as ArrowLeft,
  ExclamationCircleOutlined as AlertCircle,
  ExportOutlined as ExternalLink,
  LoadingOutlined as Loader2,
  SearchOutlined as Search,
} from "@ant-design/icons";
import { Button, Card, Input, Typography } from "@/lib/antd";
import { FadeUp } from "../components/route-motion";
import { resolveJbrowseBaseUrl } from "../lib/deployment";
import { SOYBEAN_CHROMOSOMES } from "../lib/format";
import {
    buildInitMessage,
    parseJbrowseMessage,
    newSessionId,
    type InitPayload,
    type LocusChangePayload,
} from "../lib/jbrowse-bridge";

/** Search params of the /browser route (deep-link contract with JBrowse). */
export interface BrowserSearchParams {
    assembly: string;
    /** 1-based inclusive locus, e.g. "chr01:1-1000000" (legacy alias: loc). */
    locus: string;
    /** Track IDs to display. */
    tracks?: string[];
    /** Data release tag. */
    release?: string;
    /** Same-site path to return to (whitelist-validated). */
    returnTo?: string;
}

export const Route = createFileRoute("/browser")({
    component: BrowserComponent,
    validateSearch: (search: Record<string, unknown>): BrowserSearchParams => {
        const rawLocus = search.locus ?? search.loc;
        const rawTracks = search.tracks;
        const tracks = Array.isArray(rawTracks)
            ? rawTracks.map(String).filter(Boolean)
            : rawTracks == null
                ? undefined
                : String(rawTracks)
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean);
        return {
            assembly: search.assembly == null ? "" : String(search.assembly).trim(),
            locus: rawLocus == null ? "chr01" : String(rawLocus),
            tracks: tracks && tracks.length > 0 ? tracks : undefined,
            release: search.release == null ? CONFIGURED_RELEASE : String(search.release),
            returnTo: search.returnTo == null ? undefined : String(search.returnTo),
        };
    },
});

// Configurable JBrowse URL. An empty value deliberately resolves to the
// same-origin /jbrowse path; production must never iframe localhost.
const JBROWSE_BASE = resolveJbrowseBaseUrl(import.meta.env.VITE_JBROWSE_URL);
const URL_BASE = typeof window !== "undefined" ? window.location.href : "http://localhost/";
const JBROWSE_ORIGIN = new URL(JBROWSE_BASE, URL_BASE).origin;
const CONFIGURED_RELEASE = import.meta.env.VITE_SOYMUTDB_RELEASE_ID?.trim() || undefined;

/** How long to wait for the JBrowse `ready` message before showing the retry panel. */
const READY_TIMEOUT_MS = 15_000;

type BridgeStatus = "loading" | "ready" | "timeout" | "error";

/**
 * Whitelist `returnTo` to prevent open redirects: only same-site absolute
 * paths are accepted (no protocol-relative "//host", no backslashes, no
 * scheme prefix such as "javascript:").
 */
export function safeReturnTo(value: string | undefined): string | undefined {
    if (!value) return undefined;
    if (
        value.startsWith("/") &&
        !value.startsWith("//") &&
        !value.includes("\\") &&
        !/^[a-z][a-z0-9+.-]*:/i.test(value)
    ) {
        return value;
    }
    console.warn(`[Browser] Ignoring unsafe returnTo value: ${value}`);
    return undefined;
}

/**
 * Deployment/assembly context gate for the browser deep link.
 *
 * JBrowse must never be opened without an explicit assembly and release: the
 * previous behaviour silently substituted `Wm82.a4.v1`, so a context-free
 * `/browser` link (or an unknown v5 name) rendered the v4 namespace under a
 * renamed assembly. Both fields are therefore required, and the route renders
 * a neutral "context unavailable" state instead of guessing.
 */
export function browserContextMissing(params: {
    assembly?: string | null;
    release?: string | null;
}): boolean {
    return !(params.assembly ?? "").trim() || !(params.release ?? "").trim();
}

/** Build the iframe URL from session params (deep-link contract). */
function buildJbrowseUrl(params: {
    assembly: string;
    locus: string;
    tracks?: string[];
    release?: string;
    portalOrigin?: string;
}): string {
    const url = new URL(JBROWSE_BASE, URL_BASE);
    url.searchParams.set("assembly", params.assembly);
    url.searchParams.set("locus", params.locus);
    if (params.tracks && params.tracks.length > 0) {
        url.searchParams.set("tracks", params.tracks.join(","));
    }
    if (params.release) url.searchParams.set("release", params.release);
    if (params.portalOrigin) url.searchParams.set("portalOrigin", params.portalOrigin);
    return url.toString();
}

function BrowserComponent() {
    const { t } = useTranslation();
    const search = Route.useSearch();
    const navigate = useNavigate();
    const contextMissing = browserContextMissing(search);

    const [locInput, setLocInput] = React.useState(search.locus);
    React.useEffect(() => setLocInput(search.locus), [search.locus]);

    const [status, setStatus] = React.useState<BridgeStatus>("loading");
    const [errorMessage, setErrorMessage] = React.useState<string | null>(null);
    const [iframeKey, setIframeKey] = React.useState(0);
    const [sessionId, setSessionId] = React.useState(() => newSessionId());

    const iframeRef = React.useRef<HTMLIFrameElement | null>(null);
    const initSentRef = React.useRef(false);
    // What JBrowse last told us it is showing (locus/assembly/tracks). Used to
    // avoid echo loops when URL updates originate from the iframe itself.
    const jbrowseMirrorRef = React.useRef({
        assembly: search.assembly,
        locus: search.locus,
        tracks: (search.tracks ?? []).join(","),
    });
    const latestRef = React.useRef({ search, status });
    latestRef.current = { search, status };

    // Snapshot of the deep-link session used to build the iframe URL. The
    // iframe is NOT reloaded for locus/track changes after it becomes ready —
    // those flow over the bridge instead (prevents reload loops on every pan).
    const [session, setSession] = React.useState(() => ({
        assembly: search.assembly,
        locus: search.locus,
        tracks: search.tracks ?? [],
        release: search.release,
    }));

    const portalOrigin = typeof window !== "undefined" ? window.location.origin : JBROWSE_ORIGIN;
    const jbrowseSrc = React.useMemo(
        () => buildJbrowseUrl({ ...session, portalOrigin }),
        [session, portalOrigin],
    );
    const newTabSrc = React.useMemo(() => buildJbrowseUrl({ ...session }), [session]);
    const safeReturn = React.useMemo(() => safeReturnTo(search.returnTo), [search.returnTo]);

    /** Send the full deep-link state into the iframe (idempotent for JBrowse). */
    const postInit = React.useCallback(
        (s: BrowserSearchParams) => {
            const iframe = iframeRef.current;
            if (!iframe?.contentWindow) return;
            const payload: InitPayload = {
                assembly: s.assembly,
                locus: s.locus,
                tracks: s.tracks ?? [],
                release: s.release,
                sessionId,
            };
            iframe.contentWindow.postMessage(buildInitMessage(payload), JBROWSE_ORIGIN);
        },
        [sessionId],
    );

    // Reset bridge state whenever the iframe session is (re)created. The
    // timeout only flips "loading" -> "timeout"; a late `ready` still recovers.
    React.useEffect(() => {
        if (contextMissing) {
            setStatus("error");
            setErrorMessage("A release and assembly are required to open the genome browser.");
            return;
        }
        setStatus("loading");
        setErrorMessage(null);
        initSentRef.current = false;
        const timer = window.setTimeout(() => {
            setStatus((prev) => (prev === "loading" ? "timeout" : prev));
        }, READY_TIMEOUT_MS);
        return () => window.clearTimeout(timer);
    }, [contextMissing, iframeKey]);

    // Incoming bridge messages from the JBrowse iframe.
    React.useEffect(() => {
        const handleMessage = (event: MessageEvent) => {
            const msg = parseJbrowseMessage(event, JBROWSE_ORIGIN, iframeRef.current?.contentWindow ?? null);
            if (!msg) return; // already warned inside the validator

            const latest = latestRef.current;
            switch (msg.type) {
                case "ready": {
                    // Only the first ready of a session triggers `init`.
                    if (initSentRef.current) break;
                    initSentRef.current = true;
                    setStatus("ready");
                    postInit(latest.search);
                    break;
                }
                case "error": {
                    const payload = msg.payload as { message?: unknown } | undefined;
                    setErrorMessage(
                        typeof payload?.message === "string" && payload.message
                            ? payload.message
                            : t("browser.loadError"),
                    );
                    setStatus("error");
                    break;
                }
                case "locus-change": {
                    const payload = msg.payload as LocusChangePayload | undefined;
                    if (!payload || typeof payload.locus !== "string" || !payload.locus) {
                        console.warn("[Browser] Ignoring malformed locus-change message", msg);
                        return;
                    }
                    jbrowseMirrorRef.current = {
                        assembly:
                            typeof payload.assembly === "string"
                                ? payload.assembly
                                : latest.search.assembly,
                        locus: payload.locus,
                        tracks: Array.isArray(payload.tracks)
                            ? payload.tracks.join(",")
                            : (latest.search.tracks ?? []).join(","),
                    };
                    if (payload.locus !== latest.search.locus) {
                        navigate({
                            to: "/browser",
                            search: {
                                ...latest.search,
                                locus: payload.locus,
                                tracks:
                                    Array.isArray(payload.tracks) && payload.tracks.length > 0
                                        ? payload.tracks
                                        : latest.search.tracks,
                            },
                            replace: true,
                        });
                    }
                    break;
                }
                case "selection-change":
                    // Optional message — reserved for future use; nothing to do.
                    break;
                default:
                    console.warn(`[Browser] Unknown bridge message type: ${String(msg.type)}`);
            }
        };
        window.addEventListener("message", handleMessage);
        return () => window.removeEventListener("message", handleMessage);
    }, [navigate, postInit, t]);

    // Push URL-initiated changes (search form, chromosome chips, back/forward)
    // into the ready iframe without reloading it. Changes that originated from
    // JBrowse itself are skipped via the mirror (avoids echo loops).
    React.useEffect(() => {
        if (status !== "ready") return;
        const mirror = jbrowseMirrorRef.current;
        const tracksKey = (search.tracks ?? []).join(",");
        if (
            search.locus === mirror.locus &&
            search.assembly === mirror.assembly &&
            tracksKey === mirror.tracks
        ) {
            return;
        }
        postInit(search);
    }, [search, status, postInit]);

    const handleRetry = React.useCallback(() => {
        setSessionId(newSessionId());
        setSession({
            assembly: search.assembly,
            locus: search.locus,
            tracks: search.tracks ?? [],
            release: search.release,
        });
        jbrowseMirrorRef.current = {
            assembly: search.assembly,
            locus: search.locus,
            tracks: (search.tracks ?? []).join(","),
        };
        setIframeKey((k) => k + 1);
    }, [search]);

    const handleLocate = React.useCallback(
        (next: string) => {
            navigate({ to: "/browser", search: { ...search, locus: next } });
        },
        [navigate, search],
    );

    if (contextMissing) {
        return (
            <main className="container-prose section-rhythm" data-testid="browser-missing-context">
                <Card>
                    {/* The gate stands in for the whole page, so its message is
                        that page's top heading — the loaded view below carries
                        the h1 itself. */}
                    <Typography.Title level={1}>{t("browser.contextMissingTitle")}</Typography.Title>
                    <Typography.Paragraph type="secondary">
                        {t("browser.contextMissingDescription")}
                    </Typography.Paragraph>
                </Card>
            </main>
        );
    }

    return (
        <div className="container-prose section-rhythm">
            <FadeUp>
                <div className="flex flex-wrap items-end justify-between gap-4">
                    <div>
                        <h1 className="eyebrow">{t("browser.title")}</h1>
                        <h2 className="mt-2 font-display text-4xl font-semibold tracking-tight">
                            {t("browser.subtitle")}
                        </h2>
                    </div>
                    <div className="flex items-center gap-2">
                        {safeReturn && (
                            <Button type="text" size="small" href={safeReturn} rel="noopener noreferrer" icon={<ArrowLeft className="size-4" aria-hidden />}>
                                {t("browser.back")}
                            </Button>
                        )}
                        <Button type="default" size="small" href={newTabSrc} target="_blank" rel="noopener noreferrer" icon={<ExternalLink className="size-4" aria-hidden />}>
                            {t("browser.openInNewTab")}
                        </Button>
                    </div>
                </div>
            </FadeUp>

            <Card
                className="mt-10"
                title={
                    <div>
                        <Typography.Title level={5} className="flex items-center gap-2">
                            <Microscope className="size-5 text-primary" aria-hidden />
                            {t("browser.title")}
                        </Typography.Title>
                        <Typography.Text type="secondary">
                            {t("browser.loading")}
                        </Typography.Text>
                        {/*
                          Bridge state marker. `browser-ready` exists only once
                          JBrowse has posted its validated `ready` envelope, so
                          a deployed E2E run can assert success without relying
                          on timers or the iframe load event.
                        */}
                        {status === "ready" && (
                            <span data-testid="browser-ready" className="sr-only">
                                {t("browser.ready")}
                            </span>
                        )}
                    </div>
                }
            >
                    <form
                        onSubmit={(e) => {
                            e.preventDefault();
                            const next = locInput.trim();
                            if (next) handleLocate(next);
                        }}
                        className="mb-4 flex gap-2"
                        role="search"
                    >
                        <div className="relative flex-1">
                            <Search
                                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
                                aria-hidden
                            />
                            <Input
                                value={locInput}
                                onChange={(e) => setLocInput(e.target.value)}
                                placeholder={t("browser.searchPlaceholder")}
                                aria-label={t("browser.location")}
                                data-testid="browser-locus-input"
                                className="h-12 pl-9"
                            />
                        </div>
                        <Button type="primary" htmlType="submit">{t("browser.go")}</Button>
                    </form>

                    <div className="flex flex-wrap gap-1">
                        {SOYBEAN_CHROMOSOMES.slice(0, 10).map((c) => (
                            <Button
                                key={c}
                                type={search.locus === c ? "primary" : "default"}
                                size="small"
                                className="px-2.5 font-mono text-xs"
                                onClick={() => handleLocate(c)}
                            >
                                {c.replace("chr", "")}
                            </Button>
                        ))}
                    </div>

                    <div className="relative mt-4 overflow-hidden rounded-lg border">
                        {/* Loading overlay — shown until JBrowse posts `ready` */}
                        {status === "loading" && (
                            <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-muted/50">
                                <Loader2 className="size-8 animate-spin text-primary" aria-hidden />
                                <p className="mt-3 text-sm text-muted-foreground">
                                    {t("browser.loading")}
                                </p>
                            </div>
                        )}

                        {/* Timeout overlay — no `ready` within 15s: still loading + retry */}
                        {status === "timeout" && (
                            <div
                                data-testid="browser-timeout"
                                className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-card p-8 text-center"
                            >
                                <Loader2 className="size-8 animate-spin text-primary" aria-hidden />
                                <h3 className="mt-4 font-display text-lg font-semibold">
                                    {t("browser.stillLoading")}
                                </h3>
                                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                                    {t("browser.stillLoadingDesc", { url: JBROWSE_BASE })}
                                </p>
                                <div className="mt-5 flex flex-wrap justify-center gap-3">
                                    <Button type="default" size="small" onClick={handleRetry} icon={<Loader2 className="size-4" aria-hidden />}>
                                        {t("browser.retry")}
                                    </Button>
                                    <Button type="default" size="small" href={newTabSrc} target="_blank" rel="noopener noreferrer" icon={<ExternalLink className="size-4" aria-hidden />}>
                                        {t("browser.openInNewTab")}
                                    </Button>
                                </div>
                            </div>
                        )}

                        {/* Error overlay — `error` message from JBrowse or iframe load failure */}
                        {status === "error" && (
                            <div
                                data-testid="browser-error"
                                className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-card p-8 text-center"
                            >
                                <AlertCircle className="size-10 text-destructive" aria-hidden />
                                <h3 className="mt-4 font-display text-lg font-semibold">
                                    {t("browser.loadError")}
                                </h3>
                                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                                    {errorMessage ?? t("browser.loadErrorDetail", { url: JBROWSE_BASE })}
                                </p>
                                <div className="mt-5 flex flex-wrap justify-center gap-3">
                                    <Button type="default" size="small" onClick={handleRetry} icon={<Loader2 className="size-4" aria-hidden />}>
                                        {t("browser.retry")}
                                    </Button>
                                    <Button type="default" size="small" href={newTabSrc} target="_blank" rel="noopener noreferrer" icon={<ExternalLink className="size-4" aria-hidden />}>
                                        {t("browser.openInNewTab")}
                                    </Button>
                                </div>
                            </div>
                        )}

                        <iframe
                            key={iframeKey}
                            ref={iframeRef}
                            src={jbrowseSrc}
                            data-testid="browser-iframe"
                            data-bridge-status={status}
                            title={t("browser.iframeTitle")}
                            className="h-[600px] w-full"
                            loading="lazy"
                            allow="clipboard-read; clipboard-write"
                            onError={() => {
                                setErrorMessage(t("browser.loadError"));
                                setStatus("error");
                            }}
                        />
                    </div>
            </Card>
        </div>
    );
}
