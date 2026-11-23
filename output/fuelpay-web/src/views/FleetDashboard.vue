<script setup lang="ts">
/**
 * The fleet, on a map of Nigeria.
 *
 * Geography is the primary index for this product: a branch running dry in Kano
 * and one in Ikeja are the same colour of urgent in a card grid, but a very
 * different dispatch decision. Every site already carried real coordinates and
 * nothing had ever drawn them.
 *
 * Nothing the card dashboard did was dropped — the bulk rollup, the generator
 * list with its filters and the incidents feed all moved into the rail.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Alert } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import FleetMap from '@/components/map/FleetMap.vue'
import MapLegend from '@/components/map/MapLegend.vue'
import SiteRail from '@/components/map/SiteRail.vue'
import { useFleetStore } from '@/stores/fleet'
import { useIncidentsStore } from '@/stores/incidents'
import { useSitesStore } from '@/stores/sites'
import { litres, percent } from '@/lib/format'
import { listVehicles } from '@/api/vehicles'
import type { Vehicle } from '@/api/types'

const fleet = useFleetStore()
const incidents = useIncidentsStore()
const sites = useSitesStore()

const router = useRouter()
const railOpen = ref(true)

// Tractors ride on the same map. Polled on their own: they move between the
// fleet store's refreshes, and the generator fleet does not.
const vehicles = ref<Vehicle[]>([])
async function loadVehicles() {
  try {
    vehicles.value = await listVehicles()
  } catch {
    /* the map is still useful without them */
  }
}
let vehicleTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  loadVehicles()
  vehicleTimer = setInterval(loadVehicles, 30_000)
})
onBeforeUnmount(() => vehicleTimer && clearInterval(vehicleTimer))
const mapRef = ref<InstanceType<typeof FleetMap>>()

onMounted(async () => {
  // The map draws from `fleet` alone, so it does not wait on the rollup — the
  // usage figures fill in when /sites/summary lands.
  await Promise.all([fleet.loadAll(), incidents.load()])
  sites.load()
})

const summary = computed(() => fleet.summary)
const subtitle = computed(() =>
  fleet.summary
    ? `${fleet.summary.generator_count} generators across ${fleet.siteList.length} sites`
    : undefined,
)

/** Fleet bulk total, over reporting tanks only. */
const bulkTotals = computed(() => {
  const cards = [...fleet.bulkBySite.values()]
  if (!cards.length) return null
  const capacity = cards.reduce((sum, bulk) => sum + bulk.capacityL, 0)
  const reporting = cards.filter((bulk) => bulk.levelL !== undefined)
  const level = reporting.reduce((sum, bulk) => sum + (bulk.levelL ?? 0), 0)
  return {
    capacity,
    level: reporting.length ? level : undefined,
    pct: reporting.length && capacity ? (level / capacity) * 100 : undefined,
    dark: cards.reduce((sum, bulk) => sum + (bulk.total - bulk.reporting), 0),
  }
})

const darkSensorCount = computed(() => fleet.darkSensors.length)

function toggleRail() {
  railOpen.value = !railOpen.value
  // The map's column changes width with no window resize event, so Leaflet has
  // to be told — otherwise it renders grey where the container grew.
  window.setTimeout(() => mapRef.value?.invalidate(), 220)
}
</script>

<template>
  <div class="page">
    <PageHeader title="Fleet" :subtitle="subtitle" />

    <Alert v-if="fleet.error" type="error" :message="fleet.error" class="mb-4" show-icon />

    <section class="tiles" aria-label="Fleet summary">
      <template v-if="summary">
        <StatTile
          v-if="bulkTotals"
          class="tiles__primary"
          label="Bulk reserve"
          :value="bulkTotals.level ?? 0"
          unit="L"
          emphasis="primary"
          :sub="
            bulkTotals.level !== undefined
              ? `${percent(bulkTotals.pct)} of ${litres(bulkTotals.capacity)}` +
                (bulkTotals.dark ? ` · ${bulkTotals.dark} tank(s) dark` : '')
              : 'no bulk sensor reporting'
          "
        />
        <StatTile
          label="Day tanks"
          :value="summary.total_fuel_l"
          unit="L"
          :sub="`${percent(summary.fill_pct)} of ${litres(summary.total_capacity_l)}`"
        />
        <StatTile
          label="Running"
          :value="summary.running_count"
          :sub="`of ${summary.generator_count} active`"
        />
        <StatTile
          label="Below reorder"
          :value="summary.below_reorder_threshold"
          :tone="summary.below_reorder_threshold > 0 ? 'watch' : 'default'"
          sub="needs a tanker"
        />
        <StatTile
          label="Sensors dark"
          :value="darkSensorCount"
          :tone="darkSensorCount > 0 ? 'watch' : 'default'"
          sub="tanks we cannot see"
        />
        <StatTile
          label="Drained 24h"
          :value="summary.drained_l_24h"
          unit="L"
          :tone="summary.drained_l_24h > 0 ? 'critical' : 'default'"
          sub="suspected theft"
        />
      </template>
      <template v-else>
        <AppCard v-for="n in 6" :key="n" padding="sm" :class="n === 1 ? 'tiles__primary' : ''">
          <SkeletonBlock height="11px" width="60%" />
          <SkeletonBlock height="26px" class="mt-2" width="80%" />
        </AppCard>
      </template>
    </section>

    <div class="toolbar">
      <MapLegend />
      <button
        type="button"
        class="rail-toggle"
        :aria-expanded="railOpen"
        aria-controls="site-rail"
        @click="toggleRail"
      >
        {{ railOpen ? 'Hide panel' : 'Show panel' }}
      </button>
    </div>

    <!-- The rail comes FIRST in the DOM so a keyboard user reaches the site
         list before eight map markers; CSS grid areas put it on the right. -->
    <div class="workspace" :class="{ 'workspace--wide': !railOpen }">
      <div id="site-rail" class="cell cell--rail" :hidden="!railOpen">
        <SiteRail :rows="sites.rows" :selected-id="sites.selectedId" @select="sites.select" />
      </div>

      <div class="cell cell--map">
        <FleetMap
          ref="mapRef"
          :rows="sites.rows"
          :selected-id="sites.selectedId"
          :vehicles="vehicles"
          @select="sites.select"
          @open-vehicle="(id) => router.push({ name: 'vehicle', params: { id } })"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 90rem; margin: 0 auto; padding: 20px 16px 32px }
@media (min-width: 768px) { .page { padding: 24px 24px 40px } }

.tiles {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 12px;
}
@media (min-width: 768px) { .tiles { grid-template-columns: repeat(3, minmax(0, 1fr)) } }
@media (min-width: 1280px) { .tiles { grid-template-columns: repeat(6, minmax(0, 1fr)) } }
.tiles__primary { grid-column: span 2 }

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
  min-width: 0;
}

.rail-toggle {
  flex: 0 0 auto;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-muted);
  background: var(--surface-raised);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-control);
  cursor: pointer;
}
.rail-toggle:hover { color: var(--ink); background: var(--surface-sunken) }

/* Map first visually on narrow screens, rail beneath it. Both cells carry
   min-width/min-height 0 so the map can shrink — without it the column's
   content-driven minimum forces horizontal overflow at 360px. */
.workspace {
  display: grid;
  gap: 12px;
  grid-template-areas: 'map' 'rail';
  grid-template-columns: minmax(0, 1fr);
}
.cell { min-width: 0; min-height: 0 }
.cell--map { grid-area: map; height: clamp(300px, 52svh, 420px) }
.cell--rail { grid-area: rail; max-height: 460px; display: flex }
.cell--rail > * { flex: 1; min-height: 0 }

@media (min-width: 1024px) {
  .workspace {
    grid-template-areas: 'map rail';
    grid-template-columns: minmax(0, 1fr) 320px;
    height: clamp(520px, calc(100svh - 300px), 780px);
  }
  .cell--map { height: 100% }
  .cell--rail { max-height: none; height: 100% }
  .workspace--wide { grid-template-areas: 'map'; grid-template-columns: minmax(0, 1fr) }
}

@media (min-width: 1280px) {
  .workspace { grid-template-columns: minmax(0, 1fr) 360px }
}
</style>
