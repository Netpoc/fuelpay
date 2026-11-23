<script setup lang="ts">
/**
 * Where a tractor has been: its field, its yard, and the GPS track, coloured
 * by operation. Field passes show up as a tight back-and-forth fill inside the
 * rectangle; anything that strays outside it is exactly what to look at.
 */
import { computed, onMounted, ref, watch } from 'vue'
import L from 'leaflet'

import { useLeafletMap } from '@/composables/useLeafletMap'
import type { VehicleDetail, VehicleTrack } from '@/api/types'
import { OPERATION_SPEC } from '@/lib/operations'
import { tractorIcon } from './marker'
import { BRAND } from '@/theme/tokens'

const props = defineProps<{ vehicle: VehicleDetail; track: VehicleTrack | null }>()

const container = ref<HTMLElement>()
const leaflet = useLeafletMap(container, { maxZoom: 16 })
let base: L.LayerGroup | null = null
let trail: L.LayerGroup | null = null
let fitted = false

function drawBase() {
  if (!base) return
  base.clearLayers()
  L.polygon(props.vehicle.field_polygon, {
    color: BRAND.saffron,
    weight: 2,
    dashArray: '6 4',
    fillOpacity: 0.06,
  })
    .bindTooltip('Field', { direction: 'center' })
    .addTo(base)
  L.circleMarker([props.vehicle.yard_latitude, props.vehicle.yard_longitude], {
    radius: 7,
    color: BRAND.ivory,
    weight: 2,
    fillColor: BRAND.night3,
    fillOpacity: 1,
  })
    .bindTooltip('Yard', { permanent: true, direction: 'top', offset: [0, -6] })
    .addTo(base)
  const latest = props.vehicle.latest
  if (latest) {
    L.marker([latest.latitude, latest.longitude], {
      icon: tractorIcon(props.vehicle.name, latest),
      keyboard: false,
      zIndexOffset: 1000,
    }).addTo(base)
  }
}

function drawTrail() {
  if (!trail) return
  trail.clearLayers()
  for (const segment of props.track?.segments ?? []) {
    const spec = OPERATION_SPEC[segment.operation]
    L.polyline(
      segment.coordinates.map(([lon, lat]) => [lat, lon] as [number, number]),
      { color: spec.color, weight: spec.work ? 2 : 3, opacity: spec.work ? 0.8 : 0.9 },
    ).addTo(trail)
  }
}

function fit() {
  const map = leaflet.map
  if (!map || fitted) return
  const points: L.LatLngExpression[] = [
    ...props.vehicle.field_polygon,
    [props.vehicle.yard_latitude, props.vehicle.yard_longitude],
  ]
  map.fitBounds(L.latLngBounds(points).pad(0.15), { animate: false })
  fitted = true
}

onMounted(() => {
  const map = leaflet.create()
  base = L.layerGroup().addTo(map)
  trail = L.layerGroup().addTo(map)
  drawTrail()
  drawBase()
  fit()
})

watch(() => props.vehicle, drawBase)
watch(() => props.track, drawTrail)

const legend = computed(() => {
  const seen = new Set(props.track?.segments.map((s) => s.operation) ?? [])
  return [...seen].map((op) => ({ op, ...OPERATION_SPEC[op] }))
})
</script>

<template>
  <div class="wrap">
    <div ref="container" class="map" role="region" :aria-label="`Map of ${vehicle.name}'s track`" />
    <ul v-if="legend.length" class="legend" aria-label="Track colours">
      <li v-for="item in legend" :key="item.op">
        <span class="swatch" :style="{ background: item.color }" />{{ item.label }}
      </li>
    </ul>
  </div>
</template>

<style scoped>
.wrap { display: flex; flex-direction: column; gap: 8px }
.map {
  height: 340px; width: 100%;
  border-radius: var(--radius-card);
  background: var(--surface-sunken);
}
@media (min-width: 768px) { .map { height: 420px } }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; list-style: none; margin: 0; padding: 0; font-size: 12px; color: var(--ink-muted) }
.legend li { display: inline-flex; align-items: center; gap: 6px }
.swatch { width: 14px; height: 3px; border-radius: 2px }
</style>
