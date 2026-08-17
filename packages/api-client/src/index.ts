/**
 * @soymutdb/api-client — Typed API client for SoyMutDB.
 *
 * Fetch-based. `request` is the pure transport; `http` is the coordinated
 * variant (refresh-on-401, retry, logout events). Reads VITE_API_BASE_URL.
 */

export {
  request,
  apiBaseUrl,
  setAuthTokens,
  clearAuth,
  getAccessToken,
  ApiError,
  TimeoutPresets,
  isTimeoutError,
  withRetry,
  type RequestOptions,
} from "./client";

export {
  http,
  authRequest,
  refreshAccessToken,
  restoreSession,
  onAuthLogout,
  clearLegacyTokens,
  setAccessToken,
  AUTH_REFRESH_PATH,
} from "./auth";

export * from "./genes";
export * from "./variants";
export * from "./blast";
export * from "./mutant-lines";
export * from "./releases";
export * from "./search";
export * from "./stats";
export * from "./tracks";
export * from "./downloads";
export * from "./expression";
export * from "./homolog";
export * from "./sra";
export * from "./analyses";
export * from "./tools";
export * from "./news";
export * from "./site";
export * from "./admin-news";
export * from "./admin-uploads";
export * from "./page-definitions";

export * from "./capabilities";
