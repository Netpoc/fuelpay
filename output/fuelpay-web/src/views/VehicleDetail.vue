<script setup lang="ts">
/**
 * One tractor: where it is, what it is doing, how much fuel it has, and every
 * way that fuel can go missing.
 *
 * While its history is still being generated the page says so and waits,
 * rather than rendering empty charts that read as a broken sensor.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Alert, Progress } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeading from '@/components/ui/SectionHeading.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import DataList from '@/components/ui/DataList.vue'
import DataListItem from '@/components/ui/DataListItem.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import FuelTank from '@/components/tank/FuelTank.vue'
import IncidentRow from '@/components/incidents/IncidentRow.vue'
import TrackMap from '@/components/vehicle/TrackMap.vue'
import VehicleChart from '@/components/charts/VehicleChart.vue'
import { getVehicle, getVehicleSeries, getVehicleTrack, listVehicleEvents } from '@/api/vehicles'
import type { Event, VehicleDetail, VehicleSeries, VehicleTrack } from '@/api/types'
import { groupIncidents, isAlerting } from '@/lib/incidents'
import { OPERATION_SPEC, operationLabel } from '@/lib/operations'
import { litres, percent, relativeTime } from '@/lib/format'
import type { StatusKey } from '@/theme/tokens'
import { useFleetStore } from '@/stores/fleet'

const props = defineProps<{ id: string }>()

const vehicle = ref<VehicleDetail | null>(null)
const series = ref<VehicleSeries | null>(null)
const track = ref<VehicleTrack | null>(null)
const events = ref<Event[]>([])
const loading = ref(false)
const chartLoading = ref(false)
const error = ref<string | null>(null)

const RANGES = [
  { label: '24h', value: 24 },
  { label: '3d', value: 72 },
  { label: '7d', value: 168 },
  { label: '30d', value: 720 },
]
const hours = ref(24)

const live = computed(() => vehicle.value?.simulation_status === 'LIVE')

async function loadVehicle() {
  loading.value = !vehicle.value
  error.value = null
  try {
    vehicle.value = await getVehicle(props.id)
    document.title = `${vehicle.value.name} · FuelPay`
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load the tractor.'
  } finally {
    loading.value = false
  }
}

async function loadWindow() {
  if (!live.value) return
  chartLoading.value = true
  try {
    const since = new Date(Date.now() - hours.value * 3_600_000).toISOString()
    const [nextSeries, nextTrack, page] = await Promise.all([
      getVehicleSeries(props.id, hours.value),
      // The track is capped at a week server-side; past that it is a solid
      // block of passes anyway.
      getVehicleTrack(props.id, Math.min(hours.value, 168)),
      listVehicleEvents(props.id, { start: since }),
    ])
    series.value = nextSeries
    track.value = nextTrack
    events.value = page.items
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load history.'
  } finally {
    chartLoading.value = false
  }
}

// Refresh while generating (fast) and while live (with the ticker cadence).
let timer: ReturnType<typeof setTimeout> | null = null
function schedule() {
  timer = setTimeout(
    async () => {
      const wasLive = live.value
      await loadVehicle()
      if (live.value && !wasLive) await loadWindow()
      schedule()
    },
    live.value ? 60_000 : 2_500,
  )
}

// The header's freshness indicator reads the fleet store; a tractor-only
// tenant never visits the fleet page to load it.
const fleet = useFleetStore()
onMounted(() => {
  if (!fleet.loadedAt) fleet.loadAll()
})
onMounted(async () => {
  await loadVehicle()
  await loadWindow()
  schedule()
})
onBeforeUnmount(() => timer && clearTimeout(timer))
watch(() => props.id, async () => {
  vehicle.value = null
  await loadVehicle()
  await loadWindow()
})
watch(hours, loadWindow)

const latest = computed(() => vehicle.value?.latest ?? null)
const opSpec = computed(() => (latest.value ? OPERATION_SPEC[latest.value.operation] : null))
const opState = computed<StatusKey>(() =>
  !latest.value ? 'critical' : opSpec.value?.work ? 'ok' : 'watch',
)

const quotaTone = computed(() => {
  const t = vehicle.value?.today
  if (!t?.l_per_ha || !t.quota_l_per_ha) return 'default'
  return t.l_per_ha > t.quota_l_per_ha * 1.15 ? 'critical' : t.l_per_ha > t.quota_l_per_ha ? 'watch' : 'ok'
})
const coolantTone = computed(() => {
  const c = latest.value?.coolant_c ?? 0
  return c > 103 ? 'critical' : c > 97 ? 'watch' : 'default'
})

const incidents = computed(() =>
  groupIncidents(events.value.filter((e) => isAlerting(e.event_type))).reverse(),
)

/** One plain sentence per incident, from the event's detail. */
function explain(detail: Record<string, unknown>, type: string): string {
  const n = (v: unknown) => (typeof v === 'number' ? v.toFixed(1) : String(v ?? ''))
  if (type === 'OVERCONSUMPTION' && detail.kind === 'return_line')
    return `Level fell ${n(detail.level_drop_l)} L while the engine reported burning ${n(detail.engine_reported_l)} L — fuel leaving by the return line.`
  if (type === 'OVERCONSUMPTION' && detail.kind === 'quota')
    return `${n(detail.l_per_ha)} L/ha ${String(detail.operation ?? '').toLowerCase()} against a ${n(detail.quota_l_per_ha)} L/ha quota over ${n(detail.area_ha)} ha.`
  if (type === 'SHORT_FILL')
    return `Billed ${n(detail.billed_l)} L, the tank sensor measured ${n(detail.measured_l)} L arriving.`
  if (type === 'MISUSE' && detail.kind === 'after_hours')
    return `Engine started at ${String(detail.local_time)}, outside working hours.`
  if (type === 'MISUSE' && detail.kind === 'off_field')
    return `Left the field mid-shift for a point ${(Number(detail.distance_m) / 1000).toFixed(1)} km away.`
  if (type === 'SUSPECTED_DRAIN') return 'Level dropped with the engine off, parked in the yard.'
  return ''
}
</script>

<template>
  <div class="page">
    <template v-if="loading && !vehicle">
      <SkeletonBlock height="28px" width="40%" />
      <SkeletonBlock height="360px" class="mt-4" />
    </template>

    <Alert v-else-if="error && !vehicle" type="error" :message="error" show-icon />

    <template v-else-if="vehicle">
      <PageHeader
        :title="vehicle.name"
        :subtitle="[vehicle.make_model, vehicle.serial].filter(Boolean).join(' · ')"
        back-to="/vehicles"
        back-label="Tractors"
      >
        <template #actions>
          <StatusChip
            v-if="live"
            :state="opState"
            :label="operationLabel(latest?.operation)"
            size="sm"
          />
        </template>
      </PageHeader>

      <!-- Still generating -->
      <AppCard v-if="!live" class="gen">
        <h2>{{ vehicle.simulation_status === 'FAILED' ? 'Data generation failed' : 'Generating 30 days of history…' }}</h2>
        <p>
          Shifts, refuels, field passes and the occasional incident are being simulated for this
          machine. The page fills in by itself when it's done.
        </p>
        <Progress
          :percent="Math.round(vehicle.backfill_progress * 100)"
          :status="vehicle.simulation_status === 'FAILED' ? 'exception' : 'active'"
        />
      </AppCard>

      <div v-else class="layout">
        <AppCard class="vessel">
          <FuelTank
            kind="DAY"
            size="lg"
            :level-l="latest?.fuel_level_l ?? 0"
            :capacity-l="vehicle.tank_capacity_l"
            :reorder-threshold-pct="15"
            :unknown="!latest"
            :engine-running="latest?.engine_on ?? false"
          />
          <p class="updated">
            {{ latest ? `reported ${relativeTime(latest.time)}` : 'no signal in the last day' }}
          </p>
        </AppCard>

        <div class="stack">
          <div class="facts">
            <StatTile
              class="facts__primary"
              label="Fuel now"
              :value="latest?.fuel_level_l ?? null"
              unit="L"
              emphasis="primary"
              :sub="latest ? `${percent(latest.fuel_level_pct, 0)} of ${litres(vehicle.tank_capacity_l)}` : 'no signal'"
              :animate="false"
            />
            <StatTile label="Worked today" :value="vehicle.today.area_ha" unit="ha" :precision="1" :sub="`${vehicle.today.distance_km} km driven`" />
            <StatTile
              label="Litres per hectare"
              :value="vehicle.today.l_per_ha"
              :display="vehicle.today.l_per_ha === null ? '—' : undefined"
              :precision="1"
              :tone="quotaTone"
              :sub="vehicle.today.quota_l_per_ha ? `quota ${vehicle.today.quota_l_per_ha} L/ha` : 'no quota for this work'"
            />
          </div>
          <div class="facts">
            <StatTile label="Engine hours" :value="latest?.engine_hours ?? null" :precision="1" unit="h" :sub="`${vehicle.today.engine_hours} h today`" />
            <StatTile label="Burned today" :value="vehicle.today.consumed_l" unit="L" :precision="1" sub="as the engine reports it" />
            <StatTile
              label="Coolant"
              :value="latest?.engine_on ? latest.coolant_c : null"
              :display="latest?.engine_on ? undefined : '—'"
              unit="°C"
              :tone="coolantTone"
              :sub="latest?.engine_on ? `oil ${latest.oil_kpa} kPa · ${latest.rpm} rpm` : 'engine off'"
            />
          </div>

          <AppCard>
            <SectionHeading title="Where it's been" :hint="track ? `${track.points} GPS points` : ''">
              <template #actions>
                <SegmentedControl v-model="hours" :options="RANGES" aria-label="Time range" />
              </template>
            </SectionHeading>
            <TrackMap class="mt-3" :vehicle="vehicle" :track="track" />
          </AppCard>

          <AppCard>
            <SectionHeading
              title="Fuel and engine"
              :hint="series ? `${series.points.length} points · ${series.bucket_minutes} min buckets` : ''"
            />
            <SkeletonBlock v-if="chartLoading && !series" height="320px" class="mt-4" />
            <VehicleChart
              v-else-if="series"
              class="mt-3"
              :points="series.points"
              :events="events"
              :capacity-l="vehicle.tank_capacity_l"
              :bucket-minutes="series.bucket_minutes"
            />
          </AppCard>

          <AppCard>
            <SectionHeading title="Incidents" :level="3" />
            <ul v-if="incidents.length" class="list">
              <li v-for="incident in incidents" :key="incident.id">
                <IncidentRow :incident="incident" :generator-name="vehicle.name" :link-to="false" />
                <p v-if="explain(incident.detail, incident.event_type)" class="why">
                  {{ explain(incident.detail, incident.event_type) }}
                </p>
              </li>
            </ul>
            <EmptyState
              v-else
              title="Nothing flagged in this window."
              description="No siphoning, short fills, over-consumption or misuse."
            />
          </AppCard>

          <AppCard>
            <DataList>
              <DataListItem label="Engine">{{ vehicle.engine_kw }} kW</DataListItem>
              <DataListItem label="Fuel sensor">
                {{ vehicle.fuel_sensor_model }} <span class="sep">·</span>
                <span class="mono text-xs">{{ vehicle.fuel_sensor_serial }}</span>
              </DataListItem>
              <DataListItem label="Main operation">{{ operationLabel(vehicle.primary_operation) }}</DataListItem>
              <DataListItem label="Field">
                {{ vehicle.field_width_m }} × {{ vehicle.field_length_m }} m
                <span class="sep">·</span>
                {{ ((vehicle.field_width_m * vehicle.field_length_m) / 10000).toFixed(1) }} ha
              </DataListItem>
              <DataListItem label="Working hours">
                {{ String(vehicle.working_hours_start).padStart(2, '0') }}:00–{{ String(vehicle.working_hours_end).padStart(2, '0') }}:00
              </DataListItem>
            </DataList>
          </AppCard>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 24px 24px 72px } }

.gen h2 { margin: 0 0 6px; font-size: 18px; font-weight: 600 }
.gen p { margin: 0 0 14px; color: var(--ink-muted); font-size: 14px; max-width: 60ch }

.layout { display: grid; gap: 14px; grid-template-columns: 1fr }
@media (min-width: 960px) { .layout { grid-template-columns: 300px minmax(0, 1fr) } }
.vessel { display: flex; flex-direction: column; align-items: center; gap: 6px; height: fit-content }
.updated { margin: 0; font-size: 11px; color: var(--ink-muted) }

.stack { display: flex; flex-direction: column; gap: 14px; min-width: 0 }
.facts { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)) }
@media (min-width: 768px) { .facts { grid-template-columns: repeat(3, minmax(0, 1fr)) } }
.facts__primary { grid-column: span 2 }
@media (min-width: 768px) { .facts__primary { grid-column: span 1 } }

.list { list-style: none; margin: 0; padding: 0 }
.list li + li { border-top: 1px solid var(--hairline) }
.why { margin: -4px 0 10px 34px; font-size: 12px; color: var(--ink-muted) }
.sep { margin: 0 6px; color: var(--ink-subtle) }
</style>
