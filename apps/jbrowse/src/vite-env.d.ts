/// <reference types="vite/client" />

interface ImportMetaEnv {
    readonly VITE_API_BASE_URL?: string;
    readonly VITE_JBROWSE_BASE_URL?: string;
    readonly VITE_JBROWSE_DATA_URL?: string;
}

interface ImportMeta {
    readonly env: ImportMetaEnv;
}
