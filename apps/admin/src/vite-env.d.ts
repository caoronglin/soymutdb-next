/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_BASE_URL?: string;
  readonly VITE_SOYMUTDB_RELEASE_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
