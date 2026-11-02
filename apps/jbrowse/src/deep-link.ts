/**
 * JBrowse 2 deep-link utilities for the standalone SoyMutDB genome browser.
 *
 * Supports URL parameters (shared with the portal at /browser):
 *   ?locus=chr01:1-1000000&tracks=genes,variants&assembly=Wm82v4.0&release=v4.0
 *
 * `loc` is still accepted as a legacy alias for `locus`. `portalOrigin` is an
 * internal parameter appended by the portal when embedding this app in an
 * iframe — it is never emitted by buildDeepLink().
 *
 * Coordinate conventions:
 *   - Deep links use 1-based inclusive coordinates (e.g. chr01:1-1000).
 *   - JBrowse internally uses 0-based half-open intervals.
 *   - Conversion helpers are provided below.
 */

/** Parsed deep-link parameters. */
export interface DeepLinkParams {
    /** Genomic locus, e.g. "chr01:1-1000000" (1-based inclusive). */
    locus?: string;
    /** Track IDs to display. */
    tracks?: string[];
    /** Assembly name. */
    assembly?: string;
    /** Data release tag (carried through, e.g. "v4.0"). */
    release?: string;
    /** Highlight region string. */
    highlight?: string;
    /** Gene ID to navigate to. */
    gene?: string;
    /** Variant ID to highlight. */
    variant?: string;
    /** Internal: origin of the embedding portal frame (if any). */
    portalOrigin?: string;
}

/** Parsed genomic location. */
export interface ParsedLocus {
    /** Chromosome / reference name. */
    refName: string;
    /** 1-based inclusive start. */
    start: number;
    /** 1-based inclusive end. */
    end: number;
}

/**
 * Parse a URL or query string into deep-link parameters.
 * Accepts a full URL, a query string (with leading "?"), or a search-params record.
 */
export function parseDeepLink(
    input: string | URLSearchParams | Record<string, unknown>,
): DeepLinkParams {
    const params: DeepLinkParams = {};
    const search =
        typeof input === "string"
            ? input.startsWith("?")
                ? new URLSearchParams(input)
                : new URL(input, window.location.origin).searchParams
            : input instanceof URLSearchParams
                ? input
                : toURLSearchParams(input);

    // `locus` is the canonical param; `loc` remains a legacy alias.
    const loc = search.get("locus") ?? search.get("loc");
    if (loc) params.locus = loc;

    // Accept both comma-separated and repeated `tracks` params.
    const tracksRaw = search.getAll("tracks");
    const tracks = tracksRaw
        .flatMap((t) => t.split(","))
        .map((t) => t.trim())
        .filter(Boolean);
    if (tracks.length > 0) params.tracks = tracks;

    const assembly = search.get("assembly");
    if (assembly) params.assembly = assembly;

    const release = search.get("release");
    if (release) params.release = release;

    const highlight = search.get("highlight");
    if (highlight) params.highlight = highlight;

    const gene = search.get("gene");
    if (gene) params.gene = gene;

    const variant = search.get("variant");
    if (variant) params.variant = variant;

    const portalOrigin = search.get("portalOrigin");
    if (portalOrigin) params.portalOrigin = portalOrigin;

    return params;
}

/**
 * Build a deep-link URL from the given parameters.
 * @param params Deep-link parameters.
 * @param baseUrl Base URL (defaults to current window location without query).
 * @returns A URL string with encoded query parameters.
 */
export function buildDeepLink(
    params: DeepLinkParams,
    baseUrl: string = typeof window !== "undefined"
        ? `${window.location.origin}${window.location.pathname}`
        : "/",
): string {
    const search = new URLSearchParams();

    if (params.locus) search.set("locus", params.locus);
    if (params.assembly) search.set("assembly", params.assembly);
    if (params.release) search.set("release", params.release);
    if (params.gene) search.set("gene", params.gene);
    if (params.variant) search.set("variant", params.variant);
    if (params.tracks && params.tracks.length > 0) {
        search.set("tracks", params.tracks.join(","));
    }
    if (params.highlight) search.set("highlight", params.highlight);

    // portalOrigin is intentionally never emitted in share/restore URLs.

    const query = search.toString();
    return query ? `${baseUrl}?${query}` : baseUrl;
}

/**
 * Parse a locus string into its components.
 * Accepts formats: "chr01:1-1000", "chr01:1..1000", "chr01:1,000-1,000,000".
 * @returns null if the string cannot be parsed.
 */
export function parseLocus(locus: string): ParsedLocus | null {
    const match = locus.match(/^([a-zA-Z0-9_.]+):([\d,]+)(?:\.\.|-)([\d,]+)$/);
    if (!match) return null;

    const [, refName, startStr, endStr] = match;
    const start = Number.parseInt(startStr.replace(/,/g, ""), 10);
    const end = Number.parseInt(endStr.replace(/,/g, ""), 10);
    if (Number.isNaN(start) || Number.isNaN(end)) return null;

    return { refName, start, end };
}

/**
 * Parse a JBrowse location string that may list several regions.
 * JBrowse renders multi-region viewports as space-separated loc strings
 * (e.g. "chr01:100..200 chr02:300..400"); a single region is the common case.
 * @returns the parsed regions, or null when the input is not a location.
 */
export function parseLocusList(locus: string): ParsedLocus[] | null {
    const tokens = locus.trim().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) return null;
    const parsed: ParsedLocus[] = [];
    for (const token of tokens) {
        const one = parseLocus(token);
        if (!one) return null;
        parsed.push(one);
    }
    return parsed;
}

/**
 * Format a parsed locus back into a 1-based inclusive string.
 */
export function formatLocus(locus: ParsedLocus): string {
    return `${locus.refName}:${locus.start}-${locus.end}`;
}

/**
 * Convert 1-based inclusive coordinates to 0-based half-open (JBrowse internal).
 * [1, 1000] → [0, 1000]
 */
export function toZeroBased(start: number, end: number): [number, number] {
    return [Math.max(0, start - 1), end];
}

/**
 * Convert 0-based half-open coordinates to 1-based inclusive.
 * [0, 1000] → [1, 1000]
 */
export function toOneBased(start: number, end: number): [number, number] {
    return [start + 1, end];
}

/**
 * Calculate an appropriate view window around a feature with padding.
 * @param featureStart 1-based feature start.
 * @param featureEnd 1-based feature end.
 * @param paddingPercent Percentage of feature length to pad on each side (default 20).
 * @returns 1-based inclusive window.
 */
export function calculateViewWindow(
    featureStart: number,
    featureEnd: number,
    paddingPercent = 20,
): { start: number; end: number } {
    const length = Math.max(1, featureEnd - featureStart);
    const padding = Math.max(50, (length * paddingPercent) / 100);
    return {
        start: Math.max(1, Math.floor(featureStart - padding)),
        end: Math.ceil(featureEnd + padding),
    };
}

/**
 * Build a locus string for a single point (e.g. a variant) with flanking context.
 */
export function pointToLocus(
    refName: string,
    position: number,
    flank = 500,
): string {
    const start = Math.max(1, position - flank);
    const end = position + flank;
    return `${refName}:${start}-${end}`;
}

function toURLSearchParams(record: Record<string, unknown>): URLSearchParams {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(record)) {
        if (value === undefined || value === null) continue;
        if (Array.isArray(value)) {
            search.set(key, value.join(","));
        } else {
            search.set(key, String(value));
        }
    }
    return search;
}

