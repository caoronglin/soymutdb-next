export const contentKeys = {
  all: ["admin-pages"] as const,
  pages: (params: { page: number; status: string; category: string }) =>
    ["admin-pages", params.page, params.status, params.category] as const,
  pageVersions: (pageId: string) => ["admin-pages", pageId, "versions"] as const,
} as const;
