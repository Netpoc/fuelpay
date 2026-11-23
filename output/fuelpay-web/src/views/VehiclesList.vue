<script setup lang="ts">
/** Every tractor, with what it is doing now and how much fuel it has. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Alert, Progress } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Figure from '@/components/ui/Figure.vue'
import { listVehicles } from '@/api/vehicles'
import type { Vehicle } from '@/api/types'
import { OPERATION_SPEC, operationLabel } from '@/lib/operations'
import { percent, relativeTime } from '@/lib/format'
import { useDemoStore } from '@/stores/demo'
import { useFleetStore } from '@/stores/fleet'

const demo = useDemoStore()
const vehicles = ref<Vehicle[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  try {
    vehicles.value = await listVehicles()
    error.value = null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load tractors.'
  } finally {
    loading.value = false
  }
}

let timer: ReturnType<typeof setInterval> | null = null
// The header's freshness indicator reads the fleet store; a tractor-only
// tenant never visits the fleet page to load it.
const fleet = useFleetStore()
onMounted(() => {
  if (!fleet.loadedAt) fleet.loadAll()
})
onMounted(() => {
  load()
  timer = setInterval(load, 15_000)
})
onBeforeUnmount(() => timer && clearInterval(timer))

const subtitle = computed(() => {
  const working = vehicles.value.filter((v) => v.latest && OPERATION_SPEC[v.latest.operation].work).length
  return `${vehicles.value.length} tractor${vehicles.value.length === 1 ? '' : 's'} · ${working} working now`
})
</script>

<template>
  <div class="page">
    <PageHeader title="Tractors" :subtitle="loading ? undefined : subtitle">
      <template #actions>
        <RouterLink v-if="demo.canAddTractor" :to="{ name: 'demo', query: { add: 'tractor' } }" class="add">
          + Add tractor
        </RouterLink>
      </template>
    </PageHeader>

    <Alert v-if="error" type="error" :message="error" show-icon class="mb-4" />

    <div v-if="loading" class="grid">
      <SkeletonBlock v-for="n in 3" :key="n" height="150px" />
    </div>

    <EmptyState
      v-else-if="!vehicles.length"
      title="No tractors yet."
      description="Tractors added to a demo account appear here with their live position and fuel."
    />

    <div v-else class="grid">
      <RouterLink
        v-for="v in vehicles"
        :key="v.id"
        :to="{ name: 'vehicle', params: { id: v.id } }"
        class="cardlink"
      >
        <AppCard class="card">
          <div class="head">
            <div>
              <h2>{{ v.name }}</h2>
              <p class="meta">{{ v.make_model ?? v.serial }}</p>
            </div>
            <StatusChip
              v-if="v.simulation_status === 'LIVE'"
              :state="v.latest ? (OPERATION_SPEC[v.latest.operation].work ? 'ok' : 'watch') : 'critical'"
              :label="operationLabel(v.latest?.operation)"
              size="sm"
            />
          </div>

          <template v-if="v.simulation_status !== 'LIVE'">
            <p class="meta">
              {{ v.simulation_status === 'FAILED' ? 'Data generation failed' : 'Generating history…' }}
            </p>
            <Progress
              :percent="Math.round(v.backfill_progress * 100)"
              size="small"
              :status="v.simulation_status === 'FAILED' ? 'exception' : 'active'"
            />
          </template>

          <template v-else-if="v.latest">
            <div class="bar" role="img" :aria-label="`Fuel ${percent(v.latest.fuel_level_pct, 0)}`">
              <span :style="{ width: `${Math.min(100, v.latest.fuel_level_pct)}%` }" :class="{ low: v.latest.fuel_level_pct < 20 }" />
            </div>
            <dl class="nums">
              <div><dt>Fuel</dt><dd><Figure :value="Math.round(v.latest.fuel_level_l)" unit="L" /></dd></div>
              <div><dt>Speed</dt><dd><Figure :value="Math.round(v.latest.speed_kmh)" unit="km/h" /></dd></div>
              <div><dt>Engine</dt><dd><Figure :value="v.latest.engine_hours.toFixed(0)" unit="h" /></dd></div>
            </dl>
            <p class="meta">reported {{ relativeTime(v.latest.time) }}</p>
          </template>
          <p v-else class="meta">No signal in the last day.</p>
        </AppCard>
      </RouterLink>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 24px 24px 72px } }
.grid { display: grid; gap: 14px; grid-template-columns: 1fr }
@media (min-width: 640px) { .grid { grid-template-columns: repeat(2, 1fr) } }
@media (min-width: 1100px) { .grid { grid-template-columns: repeat(3, 1fr) } }
.cardlink { color: inherit; text-decoration: none }
.card { display: flex; flex-direction: column; gap: 10px; height: 100%; transition: border-color var(--dur-micro) var(--ease-standard) }
.cardlink:hover .card { border-color: var(--accent) }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px }
h2 { margin: 0; font-size: 16px; font-weight: 600 }
.meta { margin: 0; font-size: 12px; color: var(--ink-muted) }
.bar { height: 8px; border-radius: 4px; background: var(--surface-sunken); overflow: hidden }
.bar span { display: block; height: 100%; background: var(--status-ok) }
.bar span.low { background: var(--status-critical) }
.nums { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 0 }
.nums dt { font-size: 11px; color: var(--ink-muted) }
.nums dd { margin: 0 }
.add {
  font-size: 13px; font-weight: 600; padding: 6px 12px;
  border: 1px solid var(--hairline-strong); border-radius: var(--radius-control); color: var(--ink);
}
.add:hover { border-color: var(--accent) }
</style>
