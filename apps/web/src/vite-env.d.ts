/// <reference types="vite/client" />

// Deployment inputs consumed by the Vue portal. Declared explicitly so views
// cannot read an unvalidated/untyped env value (or invent a differently named
// variable such as VITE_JBROWSE_URL) without a type error.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_BASE_URL?: string;
  readonly VITE_JBROWSE_BASE_URL?: string;
  readonly VITE_JBROWSE_ENABLED?: string;
  readonly VITE_SITE_VARIANT?: string;
  readonly VITE_SOYMUTDB_RELEASE_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
