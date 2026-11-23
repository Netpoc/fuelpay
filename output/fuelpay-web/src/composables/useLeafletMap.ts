/**
 * The imperative half of the map, kept out of the components.
 *
 * Leaflet owns its own DOM and mutates it outside Vue's reactivity, so the
 * lifecycle is explicit here for the same reason useTheme.ts writes the theme
 * attribute by hand: side effects on real DOM belong in one place where they
 * can be reasoned about and torn down.
 *
 * Deliberately NOT @vue-leaflet/vue-leaflet. That wrapper last shipped in 2023
 * and is still 0.x, and it wraps the easy 20% — everything hard here is
 * imperative and unwrapped anyway: invalidateSize on a rail collapse,
 * cross-fading the tile layer on a theme change, handing a live Vue node to
 * popup.setContent, and markercluster.
 */

import { onBeforeUnmount, watch, type Ref } from 'vue'
import { useResizeObserver } from '@vueuse/core'
import L from 'leaflet'

import { useTheme } from '@/composables/useTheme'
import type { Mode } from '@/theme/tokens'

/**
 * Esri's Light and Dark Gray Canvas — one per theme, so the basemap changes with
 * the rest of the UI instead of staying a bright rectangle on a dark screen.
 *
 * Chosen over CARTO's Positron/Dark Matter, which look right but now stamp
 * "API KEY REQUIRED" across every tile on the keyless endpoint — and still
 * answer 200 while doing it, so only looking at the image catches it. These are
 * genuinely keyless, and the muted canvas styling is what a data map wants:
 * the basemap is context, the pins are the content.
 *
 * Note the {z}/{y}/{x} order — Esri's is not the usual {z}/{x}/{y}.
 */
const TILES = {
  light:
    import.meta.env.VITE_MAP_TILES_LIGHT ??
    'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}',
  dark:
    import.meta.env.VITE_MAP_TILES_DARK ??
    'https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
} as const satisfies Record<Mode, string>

/**
 * A licence condition, not decoration. It may be made compact — `prefix: ''`
 * drops Leaflet's own flag — but never removed.
 */
const ATTRIBUTION =
  'Tiles &copy; <a href="https://www.esri.com/">Esri</a> — Esri, HERE, Garmin, ' +
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

/** Nigeria, with enough slack that the whole country clears the rail and chrome. */
export const NIGERIA_BOUNDS = L.latLngBounds([2.5, 2.0], [14.5, 15.5])

export interface LeafletMapOptions {
  /** False for the static locator map on a site page. */
  interactive?: boolean
  minZoom?: number
  maxZoom?: number
  /**
   * Fired when the basemap cannot be fetched. Pins are positioned from our own
   * coordinates and remain correct, so the caller says the basemap is missing
   * rather than letting the screen read as broken.
   */
  onTileError?: () => void
}

export function useLeafletMap(
  el: Ref<HTMLElement | undefined>,
  options: LeafletMapOptions = {},
) {
  // Esri's Gray Canvas is published to zoom 16 — past that it serves nothing,
  // so let Leaflet stop there rather than showing empty tiles.
  const { interactive = true, minZoom = 5, maxZoom = 16, onTileError } = options
  const { resolved } = useTheme()

  let map: L.Map | null = null
  let tiles: L.TileLayer | null = null
  let stopThemeWatch: (() => void) | null = null

  // Leaflet drives zoom/pan from JS, so main.css's global reduced-motion kill
  // switch cannot reach it — the animations have to be refused at construction.
  const reduced =
    typeof window !== 'undefined' &&
    window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  function setBasemap(mode: Mode) {
    if (!map) return
    const next = L.tileLayer(TILES[mode], {
      minZoom,
      maxZoom,
      attribution: ATTRIBUTION,
      crossOrigin: true,
    })
    const previous = tiles

    if (onTileError) next.on('tileerror', onTileError)

    // Cross-fade rather than swap: removing first flashes the container
    // background through for the length of a tile fetch, which is worst in
    // exactly the light -> dark direction people switch at dusk.
    next.once('load', () => previous?.remove())
    // `load` never fires with no network, so the old layer must not be immortal.
    window.setTimeout(() => previous?.remove(), 1500)

    next.addTo(map)
    tiles = next
  }

  function create(): L.Map {
    if (!el.value) throw new Error('useLeafletMap: container element is not mounted yet.')

    map = L.map(el.value, {
      zoomControl: interactive,
      dragging: interactive,
      scrollWheelZoom: interactive,
      doubleClickZoom: interactive,
      boxZoom: interactive,
      keyboard: interactive,
      touchZoom: interactive,
      attributionControl: true,
      minZoom,
      maxZoom,
      zoomAnimation: !reduced,
      fadeAnimation: !reduced,
      markerZoomAnimation: !reduced,
    })

    map.attributionControl.setPrefix('')
    setBasemap(resolved.value)
    stopThemeWatch = watch(resolved, setBasemap)

    return map
  }

  /**
   * Leaflet caches the container size at construction, so anything that resizes
   * it without a window resize event — the rail collapsing, a breakpoint
   * change, the page transition settling — leaves it rendering grey. One
   * observer covers all of them, and fires once on observe() so mount is
   * handled too.
   */
  useResizeObserver(el, () => map?.invalidateSize({ animate: false, pan: false }))

  onBeforeUnmount(() => {
    stopThemeWatch?.()
    // Under <Transition mode="out-in"> the outgoing view unmounts after the
    // transition; without this the resize/scroll listeners and RAF loop leak.
    map?.remove()
    map = null
    tiles = null
  })

  return {
    create,
    get map() {
      return map
    },
    invalidate: () => map?.invalidateSize({ animate: false, pan: false }),
    setBasemap,
    reduced,
  }
}
