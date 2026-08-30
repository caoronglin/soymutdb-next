/**
 * Admin publications client (publications bibliography) — typed wrappers over
 * the /api/v1/admin/publications endpoints.
 *
 * Contract (apps/api/app/api/v1/admin_publications.py + apps/api/app/schemas/content.py):
 *   GET    /api/v1/admin/publications                  -> PublicationListResponse
 *   POST   /api/v1/admin/publications   PublicationCreate    -> Publication (201)
 *   PUT    /api/v1/admin/publications/{id} PublicationUpdate  -> Publication
 *   DELETE /api/v1/admin/publications/{id}               -> 204
 */

import { http } from "./client";
import type { Publication } from "./publications";

export interface PublicationListResponse {
  items: Publication[];
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

export function createAdminPublication(payload: PublicationCreate): Promise<Publication> {
  return http.post<Publication>("/admin/publications", { json: payload });
}

export function updateAdminPublication(
  id: number | string,
  payload: PublicationUpdate
): Promise<Publication> {
  return http.put<Publication>(`/admin/publications/${id}`, { json: payload });
}

export function deleteAdminPublication(id: number | string): Promise<void> {
  return http.delete<void>(`/admin/publications/${id}`);
}
