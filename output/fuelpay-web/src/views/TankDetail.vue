<script setup lang="ts">
/**
 * One tank, in either tier.
 *
 * A bulk tank has no generator page to live under — it belongs to the site and
 * feeds several units — so tanks are addressable in their own right. The same
 * screen serves both tiers, differing only in what the movement figures mean:
 * a day tank burns, a bulk tank pumps out.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Alert } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import StatTile from '@/components/ui/StatTile.vue'
import Figure from '@/components/ui/Figure.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeading from '@/components/ui/SectionHeading.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import DataList from '@/components/ui/DataList.vue'
import DataListItem from '@/components/ui/DataListItem.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import FuelTank from '@/components/tank/FuelTank.vue'
import TankChart from '@/components/charts/TankChart.vue'
import IncidentRow from '@/components/incidents/IncidentRow.vue'
import { STATE_LABEL, tankState } from '@/components/tank/state'
import { getTank, getTankConsumption, getTankSeries, listEvents } from '@/api/fleet'
import type { Event, TankConsumption, TankSeries, TankState } from '@/api/types'
import { CHART_EVENT_TYPES, groupIncidents } from '@/lib/incidents'
import { litres, percent, relativeTime, signedLitres } from '@/lib/format'
import { useFleetStore } from '@/stores/fleet'

const props = defineProps<{ id: string }>()
const fleet = useFleetStore()

const tank = ref<TankState | null>(null)
const series = ref<TankSeries | null>(null)
const flow = ref<TankConsumption | null>(null)
const events = ref<Event[]>([])
const loading = ref(false)
const chartLoading = ref(false)
const error = ref<string | null>(null)

const RANGES = [
  { label: '24h', value: 24 },
  { label: '7d', value: 168 },
  { label: '30d', value: 720 },
  { label: '60d', value: 1440 },
]
const hours = ref(24)

async function loadTank() {
  loading.value = true
  error.value = null
  try {
    tank.value = await getTank(props.id)
    if (!tank.value) {
      error.value = 'Tank not found.'
      return
    }
    document.title = `${tank.value.name} · FuelPay`
    if (!fleet.siteList.length) fleet.loadAll()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load the tank.'
  } finally {
    loading.value = false
  }
}

async function loadWindow() {
  chartLoading.value = true
  try {
    const [nextSeries, page, nextFlow] = await Promise.all([
      getTankSeries(props.id, hours.value),
      listEvents({
        event_type: CHART_EVENT_TYPES,
        start: new Date(Date.now() - hours.value * 3_600_000).toISOString(),
        limit: 2000,
      }),
      // At least two days, so a 24h view still shows a completed day beside
      // today's partial one — a single in-progress row is no trend at all.
      getTankConsumption(props.id, Math.max(2, Math.ceil(hours.value / 24))),
    ])
    series.value = nextSeries
    flow.value = nextFlow
    // The events endpoint has no tank filter, so narrow client-side. Cheap at
    // fleet scale and avoids a second server round of query parameters.
    events.value = page.items.filter((event) => event.tank_id === props.id)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load tank history.'
  } finally {
    chartLoading.value = false
  }
}

onMounted(() => {
  loadTank()
  loadWindow()
})
watch(() => props.id, () => {
  loadTank()
  loadWindow()
})
watch(hours, loadWindow)

const incidents = computed(() => groupIncidents(events.value))

const site = computed(() =>
  tank.value ? fleet.sites.get(tank.value.site_id) : undefined,
)

const isBulk = computed(() => tank.value?.kind === 'BULK')

/** Only meaningful when the sensor has reported. Never derived from nothing. */
const state = computed(() =>
  tank.value?.level_pct === null || tank.value?.level_pct === undefined
    ? null
    : tankState(tank.value.level_pct, tank.value.reorder_threshold_pct),
)

const SENSOR_LABEL = { ONLINE: 'Live', STALE: 'Delayed', OFFLINE: 'No signal' } as const
const sensorTone = computed(() =>
  tank.value?.sensor_status === 'ONLINE'
    ? 'ok'
    : tank.value?.sensor_status === 'STALE'
      ? 'watch'
      : 'critical',
)

/**
 * Days with any movement, newest first.
 *
 * `samples` is surfaced beside the totals rather than hidden: a day the sensor
 * missed still reports whatever it saw, and without the count that reads as a
 * genuinely quiet day rather than a partly unobserved one.
 */
const EXPECTED_SAMPLES_PER_DAY = 288 // one per 5 simulated minutes
const flowDays = computed(() => {
  const todayKey = new Date().toDateString()
  return [...(flow.value?.days ?? [])].reverse().map((day) => {
    // Today is incomplete because it has not finished, which is not a fault
    // and must not be flagged as one — otherwise every tank looks like it has
    // a failing sensor all day, every day.
    const isToday = new Date(day.day).toDateString() === todayKey
    return {
      ...day,
      isToday,
      coverage: Math.min(1, day.samples / EXPECTED_SAMPLES_PER_DAY),
      partial: !isToday && day.samples > 0 && day.samples < EXPECTED_SAMPLES_PER_DAY * 0.9,
    }
  })
})

const movedLabel = computed(() => (isBulk.value ? 'Transferred out' : 'Burned'))
</script>

<template>
  <div class="page">
    <template v-if="loading && !tank">
      <SkeletonBlock height="28px" width="40%" />
      <SkeletonBlock height="360px" class="mt-4" />
    </template>

    <Alert v-else-if="error" type="error" :message="error" show-icon />

    <template v-else-if="tank">
      <PageHeader
        :title="tank.name"
        :subtitle="`${site?.name ?? 'Site'} · ${isBulk ? 'Bulk storage' : 'Generator day tank'}`"
      >
        <template #actions>
          <StatusChip
            :state="sensorTone"
            :label="SENSOR_LABEL[tank.sensor_status]"
            size="sm"
          />
          <StatusChip v-if="state" :state="state" :label="STATE_LABEL[state]" size="sm" />
        </template>
      </PageHeader>

      <div class="layout">
        <AppCard class="vessel">
          <FuelTank
            :kind="tank.kind"
            size="lg"
            :level-l="tank.level_l ?? 0"
            :capacity-l="tank.capacity_l"
            :reorder-threshold-pct="tank.reorder_threshold_pct"
            :unknown="tank.level_l === null"
          />
          <p v-if="tank.measured_at" class="updated">
            measured {{ relativeTime(tank.measured_at) }}
          </p>
          <p v-else class="updated">this sensor has never reported</p>

          <RouterLink
            v-if="tank.generator_id"
            :to="{ name: 'generator', params: { id: tank.generator_id } }"
            class="jump"
          >
            View the generator this feeds →
          </RouterLink>
        </AppCard>

        <div class="stack">
          <!-- A dark sensor gets said out loud rather than left to a subtle
               chip. Everything below it describes a window nobody observed. -->
          <Alert
            v-if="tank.sensor_status !== 'ONLINE'"
            :type="tank.sensor_status === 'OFFLINE' ? 'error' : 'warning'"
            show-icon
            :message="
              tank.sensor_status === 'OFFLINE'
                ? 'This sensor is not reporting'
                : 'This sensor is behind'
            "
            :description="
              tank.measured_at
                ? `Last level ${relativeTime(tank.measured_at)}. Any fuel that moved since is not in the figures below.`
                : 'No level has ever been recorded for this tank.'
            "
          />

          <div class="facts">
            <StatTile
              class="facts__primary"
              label="Level now"
              :value="tank.level_l"
              :display="tank.level_l === null ? '—' : undefined"
              unit="L"
              emphasis="primary"
              :sub="
                tank.level_pct !== null
                  ? `${percent(tank.level_pct, 0)} of ${litres(tank.capacity_l)}`
                  : 'no signal'
              "
              :animate="false"
            />
            <StatTile
              :label="movedLabel"
              :value="isBulk ? (flow?.total_transferred_l ?? null) : (flow?.total_consumed_l ?? null)"
              unit="L"
              sub="in this window"
            />
            <StatTile
              label="Delivered"
              :value="flow?.total_delivered_l ?? null"
              unit="L"
              sub="from tankers"
            />
          </div>

          <div class="facts">
            <StatTile
              label="Drained"
              :value="flow?.total_drained_l ?? null"
              unit="L"
              :tone="(flow?.total_drained_l ?? 0) > 0 ? 'critical' : 'default'"
              sub="suspected theft"
            />
            <StatTile
              label="Unverified loss"
              :value="flow?.total_unverified_loss_l ?? null"
              unit="L"
              :tone="(flow?.total_unverified_loss_l ?? 0) > 0 ? 'critical' : 'default'"
              sub="missing across an outage"
            />
            <StatTile
              label="Capacity"
              :value="tank.capacity_l"
              unit="L"
              :sub="`reorder at ${tank.reorder_threshold_pct}%`"
            />
          </div>

          <AppCard>
            <DataList>
              <DataListItem label="Tier">
                {{ isBulk ? 'Bulk storage' : 'In-built day tank' }}
              </DataListItem>
              <DataListItem label="Sensor">
                {{ tank.sensor_model }}
                <span class="sep">·</span>
                <span class="mono text-xs">{{ tank.sensor_serial }}</span>
              </DataListItem>
              <DataListItem label="Calibrated">
                {{ new Date(tank.calibrated_at).toLocaleDateString() }}
              </DataListItem>
              <DataListItem label="Reorder threshold">
                <Figure :value="tank.reorder_threshold_pct" unit="%" />
                <span class="sep">·</span>
                <Figure :value="litres((tank.capacity_l * tank.reorder_threshold_pct) / 100)" />
              </DataListItem>
              <DataListItem label="Site">{{ site?.name ?? '—' }}</DataListItem>
            </DataList>
          </AppCard>

          <AppCard>
            <SectionHeading
              title="Level and movement"
              :hint="
                series ? `${series.points.length} points · ${series.bucket_minutes} min buckets` : ''
              "
            >
              <template #actions>
                <SegmentedControl v-model="hours" :options="RANGES" aria-label="Chart range" />
              </template>
            </SectionHeading>

            <SkeletonBlock v-if="chartLoading && !series" height="320px" class="mt-4" />
            <TankChart
              v-else-if="series"
              class="mt-3"
              :points="series.points"
              :incidents="incidents"
              :capacity-l="tank.capacity_l"
              :reorder-threshold-pct="tank.reorder_threshold_pct"
              :bucket-minutes="series.bucket_minutes"
              :kind="tank.kind"
            />
          </AppCard>

          <AppCard>
            <SectionHeading title="Daily movement" :level="3" />
            <table v-if="flowDays.length" class="flow">
              <thead>
                <tr>
                  <th scope="col">Day</th>
                  <th scope="col">{{ movedLabel }}</th>
                  <th scope="col">Delivered</th>
                  <th scope="col">Lost</th>
                  <th scope="col">Coverage</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="day in flowDays" :key="day.day">
                  <th scope="row">{{ new Date(day.day).toLocaleDateString() }}</th>
                  <td>{{ litres(isBulk ? day.transferred_l : day.consumed_l) }}</td>
                  <td class="pos">
                    {{ day.delivered_l ? signedLitres(day.delivered_l) : '—' }}
                  </td>
                  <td :class="{ neg: day.drained_l + day.unverified_loss_l > 0 }">
                    {{
                      day.drained_l + day.unverified_loss_l
                        ? signedLitres(-(day.drained_l + day.unverified_loss_l))
                        : '—'
                    }}
                  </td>
                  <!-- Not decoration: a day the sensor missed still reports what
                       it saw, and the totals beside it are a floor, not a fact. -->
                  <td :class="{ partial: day.partial }">
                    <template v-if="day.samples === 0">no readings</template>
                    <template v-else-if="day.isToday">
                      {{ percent(day.coverage * 100, 0) }} <span class="sofar">so far</span>
                    </template>
                    <template v-else>{{ percent(day.coverage * 100, 0) }}</template>
                  </td>
                </tr>
              </tbody>
            </table>
            <EmptyState
              v-else
              title="No movement recorded in this window."
              description="No fuel entered or left this tank, or the sensor was not reporting."
            />
          </AppCard>

          <AppCard>
            <SectionHeading title="Incidents on this tank" :level="3" />
            <ul v-if="incidents.length" class="list">
              <li v-for="incident in incidents" :key="incident.id">
                <IncidentRow :incident="incident" :generator-name="tank.name" :link-to="false" />
              </li>
            </ul>
            <EmptyState
              v-else
              title="Nothing flagged in this window."
              description="No losses, deliveries or outages recorded against this tank."
            />
          </AppCard>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 24px 24px 72px } }

.layout { display: grid; gap: 14px; grid-template-columns: 1fr }
@media (min-width: 960px) { .layout { grid-template-columns: 320px minmax(0, 1fr) } }

.vessel { display: flex; flex-direction: column; align-items: center; gap: 6px; height: fit-content }
.updated { margin: 0; font-size: 11px; color: var(--ink-muted) }
.jump { margin-top: 8px; font-size: 12px; font-weight: 500 }

.stack { display: flex; flex-direction: column; gap: 14px; min-width: 0 }

.facts { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)) }
@media (min-width: 768px) { .facts { grid-template-columns: repeat(3, minmax(0, 1fr)) } }
.facts__primary { grid-column: span 2 }
@media (min-width: 768px) { .facts__primary { grid-column: span 1 } }

.sep { margin: 0 6px; color: var(--ink-subtle) }

.flow { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px }
.flow th, .flow td { text-align: right; padding: 6px 8px; font-variant-numeric: tabular-nums }
.flow thead th {
  font-size: 11px; font-weight: 600; color: var(--ink-muted);
  border-bottom: 1px solid var(--hairline);
}
.flow th[scope='row'], .flow thead th:first-child { text-align: left; font-weight: 500 }
.flow tbody tr + tr td, .flow tbody tr + tr th { border-top: 1px solid var(--hairline) }
.pos { color: var(--status-ok-text) }
.neg { color: var(--status-critical-text) }
.partial { color: var(--status-watch-text); font-weight: 600 }
.sofar { color: var(--ink-subtle); font-size: 11px }

.list { list-style: none; margin: 0; padding: 0 }
.list li + li { border-top: 1px solid var(--hairline) }
</style>
