/**
 * @soymutdb/api-client — Typed API client for SoyMutDB.
 *
 * Fetch-based with auth interceptors. Reads VITE_API_BASE_URL.
 */

export {
  request,
  http,
  apiBaseUrl,
  setAuthTokens,
  clearAuth,
  ApiError,
  TimeoutPresets,
  isTimeoutError,
  withRetry,
  type RequestOptions,
} from "./client";

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
