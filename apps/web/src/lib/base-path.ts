/**
 * Deployment subpath normalization.
 *
 * The implementation moved to `@soymutdb/shared/deployment` so the Vite config,
 * the build scripts and the gates share one normaliser; this module is kept as
 * the import path the app and its tests already use.
 */
export { normalizeBasePath } from "@soymutdb/shared/deployment";
