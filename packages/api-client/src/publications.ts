/**
 * Public publications client — typed wrapper over GET /api/v1/content/publications.
 *
 * Contract (apps/api/app/api/v1/content.py + apps/api/app/schemas/content.py):
 *   GET /api/v1/content/publications                -> Publication[]
 *   GET /api/v1/content/publications/{id}           -> Publication
 *
 * Bilingual fields (title_zh / authors_zh / abstract_zh) are optional; the
 * portal selects the EN/ZH variant based on the active i18n language and falls
 * back to the English value when the Chinese variant is missing.
 */

import { request } from "./client";

export interface Publication {
  id: string;
  title: string;
  title_zh: string | null;
  authors: string;
  authors_zh: string | null;
  journal: string | null;
  year: number | null;
  doi: string | null;
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

/** Fetch a single publication by id (public, no auth). */
export function getPublication(id: number | string): Promise<Publication> {
  return request<Publication>(`/content/publications/${id}`, { auth: false });
}
