<script setup lang="ts">
/**
 * The fleet, on the map.
 *
 * One pin per site, coloured by the worst state across both of its storage
 * tiers. The pin is a divIcon — real DOM — so it reads the same `--status-*`
 * custom properties as every chip in the product and re-themes with no JS.
 *
 * The map is never the only way to reach a site: markercluster removes
 * clustered markers from the DOM entirely, so at national zoom some sites would
 * be neither visible nor tabbable. The rail's site list is the equivalent path,
 * and the visually-hidden note below points a screen reader at it.
 */
import { nextTick, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet.markercluster'

import SiteSummaryCard from './SiteSummaryCard.vue'
import { pinView, sitePinIcon, worstState, type PinView } from './pin'
import { useLeafletMap, NIGERIA_BOUNDS } from '@/composables/useLeafletMap'
import { STATE_LABEL } from '@/components/tank/state'
import { tractorIcon } from '@/components/vehicle/marker'
import type { Vehicle } from '@/api/types'
import type { SiteMapRow } from '@/stores/sites'

const props = withDefaults(
  defineProps<{
    rows: SiteMapRow[]
    selectedId?: string | null
    /** Off for the single-pin locator map on a site page. */
    cluster?: boolean
    interactive?: boolean
    /** 'all' fits every pin; a site id zooms to that one. */
    fitTo?: 'all' | string
    zoom?: number
    /** Mobile machinery, drawn unclustered above the site pins. */
    vehicles?: Vehicle[]
  }>(),
  { selectedId: null, cluster: true, interactive: true, fitTo: 'all', zoom: 13, vehicles: () => [] },
)

const emit = defineEmits<{
  select: [siteId: string]
  open: [siteId: string]
  openVehicle: [vehicleId: string]
}>()

const container = ref<HTMLElement>()
const popupHost = ref<HTMLElement>()
const tilesFailed = ref(false)

const selectedRow = ref<SiteMapRow | null>(null)

// NOT destructured: `map` is a getter that is null until create() runs, and
// pulling it out here would capture that null forever — every guard below would
// return early and the map would render as an empty grey box.
const leaflet = useLeafletMap(container, {
  interactive: props.interactive,
  onTileError: () => (tilesFailed.value = true),
})
const invalidate = () => leaflet.invalidate()

let layer: L.LayerGroup | null = null
let vehicleLayer: L.LayerGroup | null = null
let popup: L.Popup | null = null
const markers = new Map<string, L.Marker>()
/** The marker that opened the popup, so focus can go back to it on close. */
let popupOwner: L.Marker | null = null

function clusterIcon(cluster: L.MarkerCluster) {
  const views = cluster
    .getAllChildMarkers()
    .map((marker) => (marker.options as { pinView?: PinView }).pinView)
    .filter((view): view is PinView => Boolean(view))

  // The WORST child, never an average — a cluster that blends a critical site
  // into three healthy ones hides the only one that matters.
  const state = worstState(views)
  const alerting = views.some((view) => view.badge)
  const worstLabel = state ? STATE_LABEL[state] : 'no signal'
  const label =
    `${views.length} sites in this area, worst is ${worstLabel}` +
    `${alerting ? ', with a live incident' : ''}. Activate to zoom in.`

  return L.divIcon({
    html:
      `<span class="fp-cluster${alerting ? ' fp-cluster--alerting' : ''}" ` +
      `data-state="${state ?? 'none'}" data-aria="${label.replace(/"/g, '&quot;')}">` +
      `<span class="fp-cluster__count">${views.length}</span></span>`,
    className: 'fp-pin-icon',
    iconSize: [46, 46],
    iconAnchor: [23, 23],
  })
}

/**
 * Lift each cluster's label onto the element Leaflet actually makes focusable.
 *
 * `iconCreateFunction` only controls the icon's inner HTML, and clusters are
 * rebuilt on every zoom, so this runs again whenever they change.
 */
function syncClusterA11y() {
  const root = container.value
  if (!root) return
  for (const node of root.querySelectorAll<HTMLElement>('.fp-cluster[data-aria]')) {
    const el = node.closest<HTMLElement>('.leaflet-marker-icon')
    if (!el) continue
    el.setAttribute('role', 'button')
    el.setAttribute('aria-label', node.dataset.aria ?? '')
  }
}

function makeLayer(): L.LayerGroup {
  if (!props.cluster) return L.layerGroup()

  return L.markerClusterGroup({
    // ~One pin wide, not the 80px default. Clustering is here to stop Ikeja and
    // Victoria Island (21 km apart, ~8px at national zoom) hiding each other —
    // not to aggregate sites the user asked to see individually.
    maxClusterRadius: 30,
    disableClusteringAtZoom: 9,
    // Zooming to bounds is honest; spiderfying draws pins where the sites are
    // not, on a screen whose whole claim is showing where things are.
    spiderfyOnMaxZoom: false,
    showCoverageOnHover: false,
    zoomToBoundsOnClick: true,
    animateAddingMarkers: false,
    iconCreateFunction: clusterIcon,
  })
}

function applyA11y(marker: L.Marker, view: PinView) {
  const el = marker.getElement()
  if (!el) return
  el.setAttribute('role', 'button')
  el.setAttribute('aria-label', view.ariaLabel)
}

function syncMarkers() {
  const instance = leaflet.map
  if (!instance || !layer) return

  const seen = new Set<string>()

  for (const row of props.rows) {
    const view = pinView(row, row.site.id === props.selectedId)
    seen.add(view.siteId)

    let marker = markers.get(view.siteId)
    if (!marker) {
      marker = L.marker([view.lat, view.lng], {
        icon: sitePinIcon(view),
        keyboard: true,
        title: view.ariaLabel,
        riseOnHover: true,
      })
      // Stashed on the marker so the cluster icon can read its children's state
      // without going back through the store.
      ;(marker.options as { pinView?: PinView }).pinView = view
      marker.on('click', () => openFor(view.siteId))
      marker.on('dblclick', () => emit('open', view.siteId))
      markers.set(view.siteId, marker)
      layer.addLayer(marker)
    } else {
      ;(marker.options as { pinView?: PinView }).pinView = view
      marker.setIcon(sitePinIcon(view))
      marker.setLatLng([view.lat, view.lng])
      marker.options.title = view.ariaLabel
    }
    applyA11y(marker, view)
  }

  for (const [id, marker] of markers) {
    if (seen.has(id)) continue
    layer.removeLayer(marker)
    markers.delete(id)
  }

  syncClusterA11y()
}

/**
 * Open the popup on one site.
 *
 * The popup body is a single Vue node kept in this component's template and
 * handed to Leaflet — not a fresh `createApp` per marker, which would have to
 * reinstall the router, Pinia and the antd config provider each time and would
 * drop the theme context.
 */
async function openFor(siteId: string) {
  const instance = leaflet.map
  const marker = markers.get(siteId)
  if (!instance || !marker || !popup) return

  emit('select', siteId)
  selectedRow.value = props.rows.find((row) => row.site.id === siteId) ?? null
  // Let the card render this site before Leaflet measures it for auto-pan.
  await nextTick()

  popupOwner = marker
  if (popupHost.value) popup.setContent(popupHost.value)
  popup.setLatLng(marker.getLatLng()).openOn(instance)
}

onMounted(async () => {
  const instance = leaflet.create()

  popup = L.popup({
    maxWidth: 320,
    minWidth: 260,
    autoPan: true,
    autoPanPadding: [16, 16],
    closeButton: true,
    keepInView: false,
    className: 'fp-popup',
  })

  instance.on('popupopen', (event) => {
    const el = event.popup.getElement()
    if (!el) return
    el.setAttribute('role', 'dialog')
    el.setAttribute('aria-label', `${selectedRow.value?.site.name ?? 'Site'} summary`)
    // Leaflet 1.9's close button is an <a> with a title but no accessible name.
    el.querySelector('.leaflet-popup-close-button')?.setAttribute('aria-label', 'Close summary')
    el.querySelector<HTMLElement>('[data-autofocus]')?.focus()
  })

  instance.on('popupclose', () => {
    // By now Leaflet has removed the popup, so anything focused inside it has
    // dropped focus to <body>. That — and only that — means the close stole
    // focus from the user, so hand it back to the marker that opened it.
    // Clicking straight onto another marker leaves focus on that marker, and
    // this correctly leaves it alone.
    const owner = popupOwner
    popupOwner = null
    if (owner && document.activeElement === document.body) owner.getElement()?.focus()
  })

  layer = makeLayer()
  instance.addLayer(layer)
  vehicleLayer = L.layerGroup().addTo(instance)
  syncMarkers()
  syncVehicles()
  fit()

  // Clusters are rebuilt on every zoom, taking their ARIA with them.
  instance.on('zoomend moveend', syncClusterA11y)
  layer.on('animationend', syncClusterA11y)
  syncClusterA11y()

  await nextTick()
  invalidate()
})

function fit() {
  const instance = leaflet.map
  if (!instance) return

  if (props.fitTo !== 'all') {
    const marker = markers.get(props.fitTo)
    if (marker) {
      instance.setView(marker.getLatLng(), props.zoom)
      return
    }
  }

  const points = [
    ...props.rows.map((row) => L.latLng(row.site.latitude, row.site.longitude)),
    ...vehiclePoints(),
  ]
  instance.fitBounds(points.length ? L.latLngBounds(points).pad(0.15) : NIGERIA_BOUNDS, {
    animate: false,
    // One pin (a single-tractor demo) would otherwise fit to the tile ceiling,
    // where the rural basemap is blank and the map reads as an empty box.
    maxZoom: 12,
  })
}

watch(
  () => props.rows,
  () => {
    syncMarkers()
    // Keep the open popup's content pointing at the freshest row.
    if (props.selectedId) {
      selectedRow.value = props.rows.find((row) => row.site.id === props.selectedId) ?? null
    }
  },
  { deep: true },
)

/** Where each tractor is now, or its yard when it has not reported today. */
function vehiclePoints(): L.LatLng[] {
  return props.vehicles.map((v) =>
    v.latest ? L.latLng(v.latest.latitude, v.latest.longitude) : L.latLng(v.yard_latitude, v.yard_longitude),
  )
}

function syncVehicles() {
  if (!vehicleLayer) return
  vehicleLayer.clearLayers()
  props.vehicles.forEach((vehicle, i) => {
    const marker = L.marker(vehiclePoints()[i]!, {
      icon: tractorIcon(vehicle.name, vehicle.latest),
      keyboard: true,
      title: vehicle.name,
      zIndexOffset: 500,
    })
    marker.on('click', () => emit('openVehicle', vehicle.id))
    marker.addTo(vehicleLayer!)
    const el = marker.getElement()
    el?.setAttribute('role', 'link')
    el?.setAttribute('aria-label', `${vehicle.name}, open tractor`)
  })
}

let fittedWithVehicles = false
watch(
  () => props.vehicles,
  (next) => {
    syncVehicles()
    // Vehicles usually arrive after the sites; refit once so a tractor-only
    // demo does not open on the whole of Nigeria.
    if (next.length && !fittedWithVehicles) {
      fittedWithVehicles = true
      fit()
    }
  },
  { deep: true },
)

watch(
  () => props.selectedId,
  (id) => {
    syncMarkers()
    if (!id) leaflet.map?.closePopup()
  },
)

defineExpose({ invalidate, focusSite: openFor })
</script>

<template>
  <div class="wrap">
    <div
      ref="container"
      class="map"
      role="region"
      aria-label="Map of monitored sites in Nigeria"
    />

    <!-- The accessible equivalent is the site list, not this map. Clustered
         markers are removed from the DOM, so the list is the only complete path. -->
    <p class="sr-only">
      This map shows {{ rows.length }} sites. The same information is available as a
      list in the sites panel.
    </p>

    <p v-if="tilesFailed" class="tile-warning" role="status">
      Basemap unavailable — pins are still positioned correctly.
    </p>

    <!-- Handed to Leaflet's popup by reference. Vue keeps owning and patching
         this node wherever Leaflet moves it to. -->
    <div class="popup-host">
      <div ref="popupHost">
        <SiteSummaryCard v-if="selectedRow" :row="selectedRow" compact />
      </div>
    </div>
  </div>
</template>

<style scoped>
.wrap { position: relative; height: 100%; min-height: 0; min-width: 0; }

/* This element IS the .leaflet-container — Leaflet is initialised on it — so it
   is styled directly. A `:deep(.leaflet-container)` rule would look for a
   DESCENDANT and never match, leaving Leaflet's default #ddd showing through in
   dark mode. Leaflet's own stylesheet sits in @layer leaflet (see
   assets/main.css); these scoped rules are unlayered and so win without
   !important. */
.map {
  height: 100%;
  width: 100%;
  min-height: 0;
  min-width: 0;
  border-radius: var(--radius-panel);
  background: var(--surface-sunken);
  font: inherit;
  /* NOT content-visibility: auto — a skipped layout would break Leaflet's tile
     measurement and leave the container grey. */
}

.map :deep(.leaflet-control-attribution) {
  background: color-mix(in srgb, var(--surface-raised) 88%, transparent);
  color: var(--ink-muted);
  font-size: 10px;
  border-radius: var(--radius-control) 0 0 0;
}
/* main.css strips underlines from anchors, which would leave the attribution —
   a licence condition — looking like plain text. Put them back explicitly. */
.map :deep(.leaflet-control-attribution a) {
  color: var(--interactive);
  text-decoration: underline;
}

.map :deep(.leaflet-bar) {
  border: 1px solid var(--hairline-strong);
  box-shadow: var(--elev-2);
}
.map :deep(.leaflet-bar a) {
  background: var(--surface-raised);
  color: var(--ink);
  border-bottom-color: var(--hairline);
}
.map :deep(.leaflet-bar a:hover) { background: var(--surface-sunken); }

.map :deep(.fp-popup .leaflet-popup-content-wrapper) {
  background: var(--surface-raised);
  color: var(--ink);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-card);
  box-shadow: var(--elev-2);
}
.map :deep(.fp-popup .leaflet-popup-content) { margin: 12px 14px; width: auto !important; }
.map :deep(.fp-popup .leaflet-popup-tip) {
  background: var(--surface-raised);
  border: 1px solid var(--hairline);
}
.map :deep(.fp-popup .leaflet-popup-close-button) { color: var(--ink-muted); }

.tile-warning {
  position: absolute;
  left: 12px;
  bottom: 12px;
  z-index: 500;
  margin: 0;
  padding: 6px 10px;
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  border: 1px solid var(--hairline);
  color: var(--ink-muted);
  font-size: 11px;
  box-shadow: var(--elev-1);
}

/* The popup body lives here until Leaflet moves it into the popup. */
.popup-host { display: none; }

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>

<!--
  Marker and cluster styling.

  NOT scoped: Leaflet builds the icon HTML itself and injects it into the marker
  pane, so a scoped data attribute never lands on it. `:global()` inside a
  scoped block is not the answer either — it silently mangles descendant
  selectors. A plain block under an `fp-` prefix is.
-->
<style>
.fp-pin-icon { background: none; border: 0; }
.fp-tractor-icon { background: none; border: 0; }

.fp-pin {
  --c: var(--status-ok);
  --t: var(--status-ok-text);
  position: relative;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  transition:
    transform var(--dur-control) var(--ease-standard),
    box-shadow var(--dur-control) var(--ease-standard);
}
.fp-pin[data-state='ok'] { --c: var(--status-ok); --t: var(--status-ok-text); }
.fp-pin[data-state='watch'],
.fp-pin[data-state='low'] { --c: var(--status-watch); --t: var(--status-watch-text); }
.fp-pin[data-state='critical'] { --c: var(--status-critical); --t: var(--status-critical-text); }

/* Soft vs solid is the second channel that keeps `watch` and `low` apart —
   they share a hue because a four-step ramp fails colourblind validation. */
.fp-pin--soft {
  background: color-mix(in srgb, var(--c) 18%, var(--surface-raised));
  color: var(--t);
  box-shadow: inset 0 0 0 1.5px var(--c), var(--elev-2);
}
.fp-pin--solid {
  background: var(--c);
  color: var(--on-solid);
  box-shadow: var(--elev-2);
}

/* No colour at all when the numbers cannot be trusted as current. A dashed ring
   reads as "unknown" rather than as a fourth status. */
.fp-pin--unknown {
  background: var(--surface-raised);
  color: var(--ink-muted);
  box-shadow: var(--elev-2);
  border: 1.5px dashed var(--hairline-strong);
}

.fp-pin:hover { transform: scale(1.08); }

/* Amber is brand, and brand is never a status — but selection is UI identity,
   not a fuel condition. It is the same role the accent plays as the active-nav
   marker in AppShell. Do not "fix" this to a status colour. */
.fp-pin--selected {
  box-shadow: 0 0 0 3px var(--accent), var(--elev-2);
  transform: scale(1.1);
}

.fp-pin__label { line-height: 1; }

.fp-pin__badge {
  position: absolute;
  top: -2px;
  right: -2px;
  display: grid;
  place-items: center;
  min-width: 16px;
  height: 16px;
  padding: 0 3px;
  border-radius: 999px;
  font-size: 9px;
  line-height: 1;
  color: var(--on-solid);
  border: 1.5px solid var(--surface-raised);
}
.fp-pin__badge[data-badge='critical'] { background: var(--status-critical); }
.fp-pin__badge[data-badge='watch'] { background: var(--status-watch); }

.fp-pin--alerting::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 999px;
  border: 2px solid var(--c);
  opacity: 0;
  animation: fp-pin-pulse 2s var(--ease-standard) infinite;
}

@keyframes fp-pin-pulse {
  0% { opacity: 0.55; transform: scale(0.9); }
  70% { opacity: 0; transform: scale(1.25); }
  100% { opacity: 0; transform: scale(1.25); }
}

/* Leaflet animates from JS, so main.css's global kill switch cannot reach the
   pulse either — refuse it explicitly. */
@media (prefers-reduced-motion: reduce) {
  .fp-pin--alerting::after { animation: none; opacity: 0.55; transform: none; }
  .fp-pin { transition: none; }
}

.fp-cluster {
  --c: var(--hairline-strong);
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 999px;
  background: var(--surface-raised);
  color: var(--ink);
  font-size: 13px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  border: 2px solid var(--c);
  box-shadow: var(--elev-2);
  cursor: pointer;
}
.fp-cluster[data-state='ok'] { --c: var(--status-ok); }
.fp-cluster[data-state='watch'],
.fp-cluster[data-state='low'] { --c: var(--status-watch); }
.fp-cluster[data-state='critical'] { --c: var(--status-critical); }
.fp-cluster--alerting { box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 35%, transparent), var(--elev-2); }
</style>
