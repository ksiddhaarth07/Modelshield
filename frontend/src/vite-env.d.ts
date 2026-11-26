/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_V1_API_URL?: string;
  readonly VITE_V2_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
