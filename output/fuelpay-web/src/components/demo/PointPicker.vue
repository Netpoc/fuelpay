<script setup lang="ts">
/**
 * Click-to-place map for the signup forms.
 *
 * Emits the clicked point; the parent decides which of its points that sets
 * (a site, a yard, a field centre). Markers are circleMarkers — vector, so
 * they need no image assets and take their colour from props, not a sprite.
 *
 * Coordinates are always editable as numbers beside the map too: a map must
 * never be the only way to enter something.
 */
import { onMounted, ref, watch } from 'vue'
import L from 'leaflet'

import { NIGERIA_BOUNDS, useLeafletMap } from '@/composables/useLeafletMap'
import { BRAND } from '@/theme/tokens'

export interface PickerPoint {
  id: string
  lat: number
  lon: number
  label: string
  /** CSS colour. Read from tokens by the parent. */
  color: string
}

const props = withDefaults(
  defineProps<{
    points: PickerPoint[]
    polygon?: [number, number][] | null
    /** Zoom used when the first point is placed. */
    placeZoom?: number
    label?: string
  }>(),
  { polygon: null, placeZoom: 14, label: 'Map. Click to place the selected point.' },
)

const emit = defineEmits<{ pick: [lat: number, lon: number] }>()

const container = ref<HTMLElement>()
const leaflet = useLeafletMap(container)
let layer: L.LayerGroup | null = null
let hadPoints = false

function draw() {
  const map = leaflet.map
  if (!map || !layer) return
  layer.clearLayers()
  if (props.polygon) {
    L.polygon(props.polygon, {
      color: getComputedStyle(container.value!).getPropertyValue('--accent').trim() || BRAND.saffron,
      weight: 2,
      fillOpacity: 0.15,
    }).addTo(layer)
  }
  for (const point of props.points) {
    L.circleMarker([point.lat, point.lon], {
      radius: 8,
      color: BRAND.ivory,
      weight: 2,
      fillColor: point.color,
      fillOpacity: 1,
    })
      .bindTooltip(point.label, { permanent: true, direction: 'top', offset: [0, -8] })
      .addTo(layer)
  }

  // First placement zooms in; later edits leave the user's view alone.
  if (!hadPoints && props.points.length) {
    const first = props.points[0]!
    map.setView([first.lat, first.lon], props.placeZoom, { animate: false })
    hadPoints = true
  }
}

onMounted(() => {
  const map = leaflet.create()
  layer = L.layerGroup().addTo(map)
  if (props.points.length) {
    const bounds = L.latLngBounds(props.points.map((p) => L.latLng(p.lat, p.lon)))
    map.fitBounds(bounds.pad(0.4), { animate: false, maxZoom: props.placeZoom })
    hadPoints = true
  } else {
    map.fitBounds(NIGERIA_BOUNDS, { animate: false })
  }
  map.on('click', (event: L.LeafletMouseEvent) => emit('pick', event.latlng.lat, event.latlng.lng))
  draw()
})

watch(() => [props.points, props.polygon], draw, { deep: true })
</script>

<template>
  <div ref="container" class="picker" role="application" :aria-label="label" />
</template>

<style scoped>
.picker {
  height: 280px;
  width: 100%;
  border-radius: var(--radius-card);
  background: var(--surface-sunken);
  border: 1px solid var(--hairline);
  cursor: crosshair;
}
@media (min-width: 768px) {
  .picker { height: 340px }
}
</style>
