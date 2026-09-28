/**
 * Public publications client — typed wrapper over GET /api/v1/content/publications.
 *
 * Contract (apps/api/app/api/v1/content.py + apps/api/app/schemas/content.py):
 *   GET /api/v1/content/publications                -> Publication[]
 *   GET /api/v1/content/publications/{doi}          -> Publication
 *
 * Bilingual fields (title_zh / authors_zh / abstract_zh) are optional; the
 * portal selects the EN/ZH variant based on the active i18n language and falls
 * back to the English value when the Chinese variant is missing.
 */

import { request } from "./client";

export interface Publication {
  /**
   * The DOI is the publication's public locator (`getPublication(doi)`).
   * There is no numeric id in the contract: the persistence key is internal.
   */
  doi: string | null;
  title: string;
  title_zh: string | null;
  authors: string;
  authors_zh: string | null;
  journal: string | null;
  year: number | null;
  pmid: string | null;
  abstract: string | null;
  abstract_zh: string | null;
  is_featured: boolean;
  created_at: string;
}

/** Fetch the latest publications (public, no auth). */
export function listPublications(): Promise<Publication[]> {
  return request<Publication[]>("/content/publications", { auth: false });
}

/**
 * Fetch a single publication by DOI (public, no auth).
 *
 * The DOI is passed through as a path segment; the server rejects anything that
 * is not a DOI, so a numeric persistence key cannot be used as a locator.
 */
export function getPublication(doi: string): Promise<Publication> {
  return request<Publication>(`/content/publications/${encodeURIComponent(doi)}`, {
    auth: false,
  });
}
