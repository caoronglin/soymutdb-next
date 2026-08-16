/**
 * Page Builder API client for the Admin console.
 *
 * Endpoints (administrator-only unless noted):
 *   GET    /admin/page-builder/registry              — server component registry
 *   GET    /admin/page-builder/pages                 — list page definitions
 *   POST   /admin/page-builder/pages                 — create a page
 *   GET    /admin/page-builder/pages/:id             — page + its versions
 *   PUT    /admin/page-builder/pages/:id/draft       — optimistic draft edit
 *   POST   /admin/page-builder/pages/:id/preview     — validate a preview
 *   GET    /admin/page-builder/pages/:id/versions    — list versions
 *   POST   /admin/page-builder/pages/:id/publish-request — request publication
 *
 * Public (unauthenticated) read: GET /page-definitions/:route
 */

import { http } from "@soymutdb/api-client";
import type {
  ComponentDescriptor,
  PageDefinition,
  PageDefinitionListResponse,
  PageDefinitionResponse,
  PageDefinitionStatus,
  PageDefinitionVersion,
  RegistryResponse,
} from "@soymutdb/shared";

export type {
  ComponentDescriptor,
  PageDefinition,
  PageDefinitionStatus,
  PageDefinitionVersion,
};

export interface PageDefinitionCreatePayload {
  route: string;
  title_key: string;
  definition: PageDefinition;
}

export interface DraftUpdatePayload {
  base_version: number;
  definition: PageDefinition;
  edit_comment?: string | null;
}

export interface PreviewPayload {
  definition: PageDefinition;
}

export interface PreviewResult {
  definition: PageDefinition;
  version_preview: number;
}

export interface PublishRequestPayload {
  version_id?: string | null;
  reason?: string | null;
}

export interface PublishRequestResult {
  page_id: string;
  version_id: string;
  version: number;
  status: PageDefinitionStatus;
  event_id: string | null;
}

export const pageBuilderApi = {
  /** Fetch the server-owned component registry (palette + property schemas). */
  registry() {
    return http.get<RegistryResponse>("/admin/page-builder/registry");
  },

  /** List page definitions. */
  list(params?: { page?: number; page_size?: number; route?: string }) {
    return http.get<PageDefinitionListResponse>("/admin/page-builder/pages", {
      params,
    });
  },

  /** Create a page (first draft version). */
  create(payload: PageDefinitionCreatePayload) {
    return http.post<PageDefinitionResponse>("/admin/page-builder/pages", {
      json: payload,
    });
  },

  /** Get a page with all its versions. */
  get(pageId: string) {
    return http.get<PageDefinitionResponse>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}`,
    );
  },

  /** Apply an optimistic draft edit (returns the new version). */
  updateDraft(pageId: string, payload: DraftUpdatePayload) {
    return http.put<PageDefinitionVersion>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}/draft`,
      { json: payload },
    );
  },

  /** Validate a preview definition without publishing. */
  preview(pageId: string, payload: PreviewPayload) {
    return http.post<PreviewResult>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}/preview`,
      { json: payload },
    );
  },

  /** List versions for a page. */
  versions(pageId: string) {
    return http.get<PageDefinitionVersion[]>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}/versions`,
    );
  },

  /** Request publication of a version (emits static_publish_requested). */
  publishRequest(pageId: string, payload: PublishRequestPayload) {
    return http.post<PublishRequestResult>(
      `/admin/page-builder/pages/${encodeURIComponent(pageId)}/publish-request`,
      { json: payload },
    );
  },
};

export default pageBuilderApi;
