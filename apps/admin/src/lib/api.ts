/**
 * Admin API access.
 *
 * Every mutating call goes through `authRequest`, which attaches the CSRF token
 * and coordinates refresh-on-401 — the same transport the portal uses, so the
 * two surfaces cannot drift on mutation protection.
 */
import { authRequest, type RequestOptions } from "@soymutdb/api-client";

export function adminRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return authRequest<T>(path, options);
}

export const adminApi = {
  get: <T>(path: string, options?: RequestOptions) =>
    adminRequest<T>(path, { ...options, method: "GET" }),
  post: <T>(path: string, options?: RequestOptions) =>
    adminRequest<T>(path, { ...options, method: "POST" }),
  patch: <T>(path: string, options?: RequestOptions) =>
    adminRequest<T>(path, { ...options, method: "PATCH" }),
  put: <T>(path: string, options?: RequestOptions) =>
    adminRequest<T>(path, { ...options, method: "PUT" }),
  delete: <T>(path: string, options?: RequestOptions) =>
    adminRequest<T>(path, { ...options, method: "DELETE" }),
};
