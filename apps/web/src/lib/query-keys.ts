/**
 * Framework-neutral TanStack query-key factories.
 *
 * The implementation now lives in the framework-neutral seam package
 * ``@soymutdb/query-keys`` so the same cache keys are shared by TanStack React
 * Query and, after the migration, TanStack Vue Query (plan.md Phase C). This
 * module is a thin re-export kept so existing Web imports keep working; new
 * routes should import from ``@soymutdb/query-keys`` directly.
 */
export { queryKeys } from "@soymutdb/query-keys";
export type { QueryKeys } from "@soymutdb/query-keys";
