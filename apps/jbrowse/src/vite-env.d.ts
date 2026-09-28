interface ImportMetaEnv {
  readonly BASE_URL: string;
  readonly PROD: boolean;
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_DEPLOYMENT_MODE?: string;
  readonly VITE_JBROWSE_DATA_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

declare module "*.css";
