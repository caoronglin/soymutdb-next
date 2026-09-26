/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_BASE_URL?: string;
  readonly VITE_SOYMUTDB_RELEASE_ID?: string;
  /** Marks the remote-administration trust channel as ready; never enables write. */
  readonly VITE_REMOTE_INSTANCES_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
