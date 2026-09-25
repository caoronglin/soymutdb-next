/**
 * @soymutdb/api-client — Typed API client for SoyMutDB.
 *
 * Fetch-based. `request` is the pure transport; `http` is the coordinated
 * variant (refresh-on-401, retry, logout events). Reads VITE_API_BASE_URL.
 */

export {
  request,
  requestBlob,
  apiBaseUrl,
  setAuthTokens,
  clearAuth,
  getAccessToken,
  setReleaseId,
  getReleaseId,
  ApiError,
  TimeoutPresets,
  isTimeoutError,
  withRetry,
  type IdempotentRetryOptions,
  type RequestOptions,
} from "./client";

export {
  http,
  authRequest,
  authRequestBlob,
  refreshAccessToken,
  restoreSession,
  onAuthLogout,
  clearLegacyTokens,
  setAccessToken,
  AUTH_REFRESH_PATH,
} from "./auth";

export { attachCsrf } from "./csrf";

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
export * from "./publications";
export * from "./admin-publications";
export * from "./admin-news";
export * from "./admin-uploads";
export * from "./admin-media";
export * from "./admin-plugins";
export * from "./admin-imports";
export * from "./admin-import-studio";
export * from "./admin-settings";
export * from "./page-definitions";

export * from "./capabilities";
export * from "./table-views";
export * from "./ontology";
export * from "./test-data-preview";
