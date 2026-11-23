/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_FUELPAY_API_KEY?: string
  /**
   * Basemap tile templates, one per theme.
   *
   * Overridable because the CARTO defaults are a free tier with no SLA — a
   * deployment should be able to point at a paid or self-hosted endpoint
   * without a code change. Whatever they point at, the attribution control
   * stays: it is a licence condition, not decoration.
   */
  readonly VITE_MAP_TILES_LIGHT?: string
  readonly VITE_MAP_TILES_DARK?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
