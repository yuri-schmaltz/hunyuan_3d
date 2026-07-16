/// <reference types="vite/client" />

interface ImportMetaEnv {
    /** Base URL of the Archeon backend (no trailing slash, no /v1). */
    readonly VITE_API_URL: string;
}

interface ImportMeta {
    readonly env: ImportMetaEnv;
}
