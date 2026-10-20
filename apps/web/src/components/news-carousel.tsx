/**
 * Shared identity for the homepage featured-news fetch.
 *
 * The old autoplay carousel component that lived here was never mounted (the
 * homepage renders the NewsCard grid); only this query key has an importer, so
 * the component and its slide helpers were removed as dead code (2026-10-18).
 */
export const NEWS_FEATURED_KEY = ["news-featured"] as const;
