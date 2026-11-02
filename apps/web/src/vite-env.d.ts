interface ImportMetaEnv {
  readonly BASE_URL: string;
  readonly PROD: boolean;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_BASE_URL?: string;
  readonly VITE_DEMO_MODE?: string;
  readonly VITE_DEPLOYMENT_MODE?: string;
  readonly VITE_JBROWSE_BASE_URL?: string;
  readonly VITE_JBROWSE_ENABLED?: string;
  readonly VITE_JBROWSE_URL?: string;
  readonly VITE_SITE_VARIANT?: string;
  readonly VITE_SOYMUTDB_RELEASE_ID?: string;
  readonly VITE_SW_ENABLED?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare const __SOYMUTDB_INTERNAL_SITE__: boolean;


