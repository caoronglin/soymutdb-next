/**
 * Admin publications client (publications bibliography) — typed wrappers over
 * the /api/v1/admin/publications endpoints.
 *
 * Contract (apps/api/app/api/v1/admin_publications.py + apps/api/app/schemas/content.py):
 *   GET    /api/v1/admin/publications                  -> PublicationListResponse
 *   POST   /api/v1/admin/publications   PublicationCreate    -> AdminPublication (201)
 *   PUT    /api/v1/admin/publications/{id} PublicationUpdate  -> AdminPublication
 *   DELETE /api/v1/admin/publications/{id}               -> 204
 */

import { http } from "./auth";
import type { Publication } from "./publications";

/**
 * Admin projection: the public `Publication` plus the persistence key the
 * management routes address by (`PUT`/`DELETE /admin/publications/{id}`).
 *
 * The public DTO has no `id` — publications are located by DOI externally — so
 * the admin surface has its own type rather than reusing the public one.
 */
export interface AdminPublication extends Publication {
  id: string;
}

export interface PublicationListResponse {
  items: AdminPublication[];
  total: number;
  page: number;
  page_size: number;
}

export interface PublicationCreate {
  title: string;
  title_zh?: string | null;
  authors: string;
  authors_zh?: string | null;
  journal?: string | null;
  year?: number | null;
  doi?: string | null;
  pmid?: string | null;
  abstract?: string | null;
  abstract_zh?: string | null;
  is_featured?: boolean;
}

export type PublicationUpdate = Partial<PublicationCreate>;

export interface AdminPublicationsParams {
  page?: number;
  page_size?: number;
  search?: string;
  is_featured?: boolean;
}

export function listAdminPublications(
  params: AdminPublicationsParams = {}
): Promise<PublicationListResponse> {
  return http.get<PublicationListResponse>("/admin/publications", {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 20,
      search: params.search,
      is_featured: params.is_featured,
    },
  });
}

export function createAdminPublication(
  payload: PublicationCreate
): Promise<AdminPublication> {
  return http.post<AdminPublication>("/admin/publications", { json: payload });
}

export function updateAdminPublication(
  id: number | string,
  payload: PublicationUpdate
): Promise<AdminPublication> {
  return http.put<AdminPublication>(`/admin/publications/${id}`, { json: payload });
}

export function deleteAdminPublication(id: number | string): Promise<void> {
  return http.delete<void>(`/admin/publications/${id}`);
}
