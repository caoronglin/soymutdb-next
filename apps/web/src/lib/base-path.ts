/**
 * Deployment subpath normalization.
 *
 * The implementation moved to `@soymutdb/shared/deployment` so the Umi config,
 * build scripts and gates share one normaliser; this module is kept as
 * the import path the app and its tests already use.
 */
export { normalizeBasePath } from "@soymutdb/shared/deployment";
