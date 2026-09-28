interface ImportMetaEnv {
  readonly BASE_URL: string;
  readonly PROD: boolean;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_BASE_URL?: string;
  readonly VITE_PUBLIC_URL?: string;
  /** Marks the remote-administration trust channel as ready; never enables write. */
  readonly VITE_REMOTE_INSTANCES_ENABLED?: string;
  readonly VITE_SOYMUTDB_RELEASE_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
