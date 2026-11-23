/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_FUELPAY_API_KEY?: string
  /** Key behind the gate's "Use the demo key" button. Hidden in prod builds when unset. */
  readonly VITE_DEMO_API_KEY?: string
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
  /**
   * Netpoc corporate site origin, e.g. https://netpoc.com — no trailing slash.
   * Powers the "No code yet? Book a PoC" links back to netpoc's /fuelpay page.
   * Unset → those links are hidden rather than pointing nowhere.
   */
  readonly VITE_NETPOC_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
