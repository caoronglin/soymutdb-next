import { request } from "./client";
import type {
  PageDefinition,
  PageDefinitionStatus,
} from "@soymutdb/shared";

/**
 * Typed public page-definition client.
 *
 *   GET /api/v1/page-definitions/{route}?version=<uuid>
 *
 * Returns the latest *published* definition for a route, or a specific
 * published version when `version` is supplied. This is the read contract
 * shared by the public Web renderer and the SSG publication pipeline.
 */

export interface PageDefinitionVersionPayload {
  id: string;
  page_id: string;
  version: number;
  status: PageDefinitionStatus;
  definition: PageDefinition;
  edited_by: string | null;
  edit_comment: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Fetch a published page definition for a route (optionally pinned version).
 * The route is passed without a leading slash (the API normalises it).
 */
export function getPageDefinition(
  route: string,
  version?: string,
): Promise<PageDefinitionVersionPayload> {
  const path = `/page-definitions/${route.replace(/^\/+/, "")}`;
  const params = version ? { version } : undefined;
  return request<PageDefinitionVersionPayload>(path, { params, auth: false });
}
