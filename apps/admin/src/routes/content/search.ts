export type ContentPageStatus = "all" | "draft" | "published" | "archived";

export interface ContentPageSearch {
  page: number;
  status: ContentPageStatus;
  category: string;
}

const STATUSES = new Set<ContentPageStatus>(["all", "draft", "published", "archived"]);

export function parseContentPageSearch(input: Record<string, unknown>): ContentPageSearch {
  const rawPage = typeof input.page === "number" ? input.page : Number(input.page);
  const status = typeof input.status === "string" && STATUSES.has(input.status as ContentPageStatus)
    ? input.status as ContentPageStatus
    : "all";
  return {
    page: Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
    status,
    category: typeof input.category === "string" ? input.category.trim() : "",
  };
}

export function serializeContentPageSearch(search: ContentPageSearch): Record<string, string | number> {
  const out: Record<string, string | number> = {};
  if (search.page > 1) out.page = search.page;
  if (search.status !== "all") out.status = search.status;
  if (search.category) out.category = search.category;
  return out;
}
