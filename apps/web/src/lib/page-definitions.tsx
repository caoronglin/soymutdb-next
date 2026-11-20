/**
 * Public PageDefinition hooks.
 *
 * Published definitions are an optional override layer over the static portal
 * routes: when the `page_builder` feature is enabled and a route has a
 * published version, the renderer draws that definition; otherwise the route
 * keeps its compiled page. A 404 (disabled feature or no published version) is
 * therefore "no override", not an error.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  getPageDefinition,
  listPublishedPageDefinitions,
  type PageDefinitionVersionPayload,
} from "@soymutdb/api-client";
import { normalizePageDefinition, type PageDefinitionV2 } from "@soymutdb/shared";
import { SITE_VARIANT } from "./site-variant";

function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

async function fetchPublished(route: string): Promise<PageDefinitionV2 | null> {
  try {
    const payload = await getPageDefinition(route);
    return normalizePageDefinition(payload.definition);
  } catch (error) {
    if (isNotFound(error)) return null;
    throw error;
  }
}

/** Latest published definition for `route`, or null when there is none. */
export function usePublishedPageDefinition(route: string) {
  const queryClient = useQueryClient();
  const normalized = route.replace(/^\/+/, "") || "/";
  return useQuery({
    queryKey: ["page-definition", SITE_VARIANT, route],
    queryFn: async () => {
      // Read the published-route list first and only request a definition for
      // a route the list names. Asking for a definition that does not exist
      // is a 404 by design, and the browser reports every one of those as a
      // failed resource -- one console error per page view on a site with no
      // published definitions at all. The list answers 200 with an empty
      // array, so the common case is a single successful request and no 404.
      //
      // The list is fetched through the query cache, so several pages on one
      // site share one request, and a disabled feature (the list itself 404s)
      // resolves to "nothing is published" rather than to a failing request.
      const list = await queryClient.ensureQueryData({
        queryKey: ["page-definition-routes", SITE_VARIANT],
        queryFn: async () => {
          try {
            return await listPublishedPageDefinitions();
          } catch (error) {
            if (isNotFound(error)) return [];
            throw error;
          }
        },
        staleTime: 60_000,
      });
      const published = list.some(
        (entry) => entry.route.replace(/^\/+/, "") === normalized,
      );
      if (!published) return null;
      return fetchPublished(route);
    },
    staleTime: 60_000,
    retry: false,
  });
}

/** Every route that currently has a published definition (SSG-safe routes). */
export function usePublishedPageRoutes() {
  return useQuery({
    queryKey: ["page-definition-routes", SITE_VARIANT],
    queryFn: async (): Promise<PageDefinitionVersionPayload[]> => {
      try {
        return await listPublishedPageDefinitions();
      } catch (error) {
        if (isNotFound(error)) return [];
        throw error;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}