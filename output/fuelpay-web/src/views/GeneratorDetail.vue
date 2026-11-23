<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Alert, Button, App as AntApp } from 'ant-design-vue'

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
import FuelTank from '@/components/tank/FuelTank.vue'
import FuelChart from '@/components/charts/FuelChart.vue'
import IncidentRow from '@/components/incidents/IncidentRow.vue'
import { STATE_LABEL, tankState } from '@/components/tank/state'
import { getGenerator, getSiteFuel, listEvents, simulateDrain, simulateRefill } from '@/api/fleet'
import { getSeries, type GeneratorSeries } from '@/api/series'
import type { Event, GeneratorDetail, SiteFuel } from '@/api/types'
import { CHART_EVENT_TYPES, groupIncidents, liveAlerts } from '@/lib/incidents'
import { hoursToEmpty, kilowatts, litres, percent, profileLabel, relativeTime } from '@/lib/format'

const props = defineProps<{ id: string }>()
const { message } = AntApp.useApp()

const detail = ref<GeneratorDetail | null>(null)
const fuel = ref<SiteFuel | null>(null)
const series = ref<GeneratorSeries | null>(null)
const events = ref<Event[]>([])
const loading = ref(false)
const chartLoading = ref(false)
const error = ref<string | null>(null)
const busy = ref(false)

const RANGES = [
  { label: '24h', value: 24 },
  { label: '7d', value: 168 },
  { label: '30d', value: 720 },
  { label: '60d', value: 1440 },
]
const hours = ref(24)

async function loadDetail() {
  loading.value = true
  error.value = null
  try {
    detail.value = await getGenerator(props.id)
    document.title = `${detail.value.name} · FuelPay`
    // Sequential rather than parallel: the site id only exists once the
    // generator has loaded.
    fuel.value = await getSiteFuel(detail.value.site.id)
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load this generator.'
  } finally {
    loading.value = false
  }
}

async function loadChart() {
  chartLoading.value = true
  try {
    const [nextSeries, page] = await Promise.all([
      getSeries(props.id, hours.value),
      listEvents({
        generator_id: props.id,
        event_type: CHART_EVENT_TYPES,
        start: new Date(Date.now() - hours.value * 3_600_000).toISOString(),
        limit: 2000,
      }),
    ])
    series.value = nextSeries
    events.value = page.items
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load the chart.'
  } finally {
    chartLoading.value = false
  }
}

const loadAll = () => Promise.all([loadDetail(), loadChart()])
onMounted(loadAll)
watch(() => props.id, loadAll)
watch(hours, loadChart)

const incidents = computed(() => groupIncidents(events.value))
const fuelPct = computed(() => detail.value?.latest?.fuel_level_pct ?? 0)
const state = computed(() => tankState(fuelPct.value, detail.value?.reorder_threshold_pct ?? 25))

/**
 * The site's bulk reserve, in the same shape the dashboard uses.
 *
 * Totals are over reporting tanks only — `bulk_tanks_reporting` vs
 * `bulk_tanks_total` from the API says whether that was all of them.
 */
const siteBulk = computed(() => {
  const row = fuel.value
  if (!row || !row.bulk.length) return null
  const threshold = Math.max(...row.bulk.map((tank) => tank.reorder_threshold_pct))
  // The emptiest reporting tank — the one that will strand the site first, and
  // so the one worth opening. Falls back to the first tank when none report.
  const reporting = row.bulk.filter((tank) => tank.level_l !== null)
  const lead = reporting.length
    ? reporting.reduce((a, b) => ((a.level_pct ?? 100) <= (b.level_pct ?? 100) ? a : b))
    : row.bulk[0]
  return {
    leadTankId: lead?.id,
    capacityL: row.bulk_capacity_l,
    levelL: row.bulk_level_l ?? undefined,
    levelPct: row.bulk_level_pct ?? undefined,
    partial: row.bulk_tanks_reporting > 0 && row.bulk_tanks_reporting < row.bulk_tanks_total,
    state: tankState(row.bulk_level_pct ?? 100, threshold),
  }
})

/** Same rule the dashboard uses, so the two cannot disagree. */
const activeAlert = computed<'drain' | 'low' | null>(() => {
  const worst = liveAlerts(incidents.value)[0]
  if (!worst) return null
  return worst.event_type === 'SUSPECTED_DRAIN' ? 'drain' : 'low'
})

/**
 * Demo controls. These drive the real simulator rather than faking anything in
 * the browser, so what lands on the chart is the same series an unprompted
 * incident produces.
 */
async function trigger(kind: 'drain' | 'refill') {
  if (!detail.value) return
  busy.value = true
  try {
    const result =
      kind === 'drain' ? await simulateDrain(detail.value.id) : await simulateRefill(detail.value.id)
    message.success(
      `${result.events.length} event(s) over ${result.steps} step(s) — tank now ${percent(result.fuel_level_pct, 0)}`,
    )
    await loadAll()
  } catch (caught) {
    message.error(caught instanceof Error ? caught.message : 'That did not work.')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="page">
    <Alert v-if="error" type="error" :message="error" show-icon class="mb-4" />

    <template v-if="loading && !detail">
      <SkeletonBlock height="28px" width="240px" />
      <SkeletonBlock height="320px" class="mt-6" radius="var(--radius-card)" />
    </template>

    <template v-else-if="detail">
      <PageHeader
        :title="detail.name"
        :subtitle="`${detail.site.name} · ${profileLabel(detail.site.profile)}`"
        back-to="/fleet"
        back-label="Fleet"
      >
        <template #meta>
          <p class="serial mono">{{ detail.serial }}</p>
        </template>
        <template #actions>
          <StatusChip :state="state" :label="STATE_LABEL[state]" />
        </template>
      </PageHeader>

      <div class="layout">
        <!-- Tank column -->
        <AppCard class="tankcard">
          <div class="tankwrap">
            <FuelTank
              v-if="detail.latest"
              size="lg"
              :level-l="detail.latest.fuel_level_l"
              :capacity-l="detail.tank_capacity_l"
              :reorder-threshold-pct="detail.reorder_threshold_pct"
              :engine-running="detail.latest.engine_running"
              :alert="activeAlert"
            />
            <p v-else class="nodata">No readings yet.</p>
          </div>
          <p v-if="detail.latest" class="updated">updated {{ relativeTime(detail.latest.time) }}</p>

          <!-- The tank is a thing in its own right, with its own sensor,
               history and incidents. This is the way in. -->
          <RouterLink
            v-if="detail.day_tank"
            :to="{ name: 'tank', params: { id: detail.day_tank.id } }"
            class="jump"
          >
            Day tank readings &amp; trends →
          </RouterLink>

          <div class="demo">
            <p class="demo__label">Demo</p>
            <div class="demo__buttons">
              <Button size="small" :loading="busy" danger @click="trigger('drain')">
                Simulate drain
              </Button>
              <Button size="small" :loading="busy" @click="trigger('refill')">Simulate refill</Button>
            </div>
            <p class="demo__note">Drives the real simulator, not a mock.</p>
          </div>
        </AppCard>

        <div class="stack">
          <!-- Runtime is the answer to "when does this site go dark", so it is
               a headline figure rather than one cell in a table. -->
          <div class="facts">
            <StatTile
              class="facts__primary"
              label="Runtime remaining"
              :value="detail.hours_to_empty"
              :display="hoursToEmpty(detail.hours_to_empty)"
              emphasis="primary"
              :sub="detail.hours_to_empty === null ? 'engine stopped' : 'at the current load'"
              :animate="false"
            />
            <StatTile
              label="Load"
              :value="detail.latest?.load_kw ?? null"
              unit="kW"
              :precision="1"
              :sub="detail.latest ? percent(detail.latest.load_pct, 0) + ' of rated' : undefined"
            />
            <StatTile
              label="Day tank"
              :value="detail.latest?.fuel_level_l ?? null"
              unit="L"
              :sub="`of ${litres(detail.tank_capacity_l)}`"
            />
            <!-- The reserve this generator actually draws on. A full day tank
                 above an empty bulk tank is hours from dark, and the day-tank
                 figure alone does not show that. Links to the emptiest bulk
                 tank, since that is the one about to run the site dry. -->
            <RouterLink
              v-if="siteBulk && siteBulk.leadTankId"
              :to="{ name: 'tank', params: { id: siteBulk.leadTankId } }"
              class="tilelink"
            >
              <StatTile
                label="Site bulk"
                :value="siteBulk.levelL ?? null"
                unit="L"
                :display="siteBulk.levelL === undefined ? '—' : undefined"
                :tone="siteBulk.state === 'critical' ? 'critical' : siteBulk.state === 'low' ? 'watch' : 'default'"
                :sub="
                  siteBulk.levelL !== undefined
                    ? `${percent(siteBulk.levelPct, 0)} of ${litres(siteBulk.capacityL)}`
                    : 'no bulk sensor reporting'
                "
              />
            </RouterLink>
            <StatTile
              v-else-if="siteBulk"
              label="Site bulk"
              :value="siteBulk.levelL ?? null"
              unit="L"
              :display="siteBulk.levelL === undefined ? '—' : undefined"
              :tone="siteBulk.state === 'critical' ? 'critical' : siteBulk.state === 'low' ? 'watch' : 'default'"
              :sub="
                siteBulk.levelL !== undefined
                  ? `${percent(siteBulk.levelPct, 0)} of ${litres(siteBulk.capacityL)}`
                  : 'no bulk sensor reporting'
              "
            />
          </div>

          <!-- A dark fuel sensor is not a fuel reading, and must never be
               rendered as one. Say so plainly instead. -->
          <Alert
            v-if="detail.day_tank && detail.day_tank.sensor_status !== 'ONLINE'"
            :type="detail.day_tank.sensor_status === 'OFFLINE' ? 'error' : 'warning'"
            show-icon
            :message="
              detail.day_tank.sensor_status === 'OFFLINE'
                ? 'Day tank sensor is not reporting'
                : 'Day tank sensor is behind'
            "
            :description="
              detail.day_tank.measured_at
                ? `Last level ${relativeTime(detail.day_tank.measured_at)}. Fuel moved since then would not appear here.`
                : 'This sensor has never reported a level.'
            "
          />

          <AppCard>
            <DataList>
              <DataListItem label="Engine">
                {{ detail.latest?.engine_running ? 'Running' : 'Stopped' }}
              </DataListItem>
              <DataListItem label="Reorder threshold">
                <Figure :value="detail.reorder_threshold_pct" unit="%" />
                <span class="sep">·</span>
                <Figure
                  :value="litres((detail.tank_capacity_l * detail.reorder_threshold_pct) / 100)"
                />
              </DataListItem>
              <DataListItem label="Rating">
                <Figure :value="detail.kva_rating" unit="kVA" /> @ pf {{ detail.power_factor }}
              </DataListItem>
              <DataListItem label="Load now">
                <Figure :value="kilowatts(detail.latest?.load_kw)" />
              </DataListItem>
              <DataListItem label="Position">
                <span class="mono text-xs">
                  {{ (detail.latest?.latitude ?? detail.site.latitude).toFixed(5) }},
                  {{ (detail.latest?.longitude ?? detail.site.longitude).toFixed(5) }}
                </span>
              </DataListItem>
              <DataListItem label="Address">{{ detail.site.address ?? '—' }}</DataListItem>
            </DataList>
          </AppCard>

          <AppCard>
            <SectionHeading
              title="Fuel usage"
              :hint="series ? `${series.points.length} points · ${series.bucket_minutes} min buckets` : ''"
            >
              <template #actions>
                <SegmentedControl v-model="hours" :options="RANGES" aria-label="Chart range" />
              </template>
            </SectionHeading>

            <SkeletonBlock v-if="chartLoading && !series" height="320px" class="mt-4" />
            <FuelChart
              v-else-if="series"
              class="mt-3"
              :points="series.points"
              :incidents="incidents"
              :capacity-l="detail.tank_capacity_l"
              :reorder-threshold-pct="detail.reorder_threshold_pct"
              :bucket-minutes="series.bucket_minutes"
            />
          </AppCard>

          <AppCard v-if="incidents.length">
            <SectionHeading title="Incidents in this window" :level="3" />
            <ul class="incidents">
              <li v-for="incident in incidents.slice(0, 8)" :key="incident.id">
                <IncidentRow :incident="incident" :link-to="false" />
              </li>
            </ul>
          </AppCard>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page { max-width: 90rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 24px 24px 72px } }

.serial { margin: 6px 0 0; font-size: 12px; color: var(--ink-muted) }

.layout { display: grid; gap: 14px; grid-template-columns: 1fr }
@media (min-width: 1024px) { .layout { grid-template-columns: minmax(230px, 300px) 1fr } }

.tankcard { display: flex; flex-direction: column; align-items: center; text-align: center }
.tankwrap { display: flex; justify-content: center; width: 100%; padding: 4px 0 }
.nodata { padding: 48px 0; font-size: 13px; color: var(--ink-muted) }
.updated { margin: 10px 0 0; font-size: 11px; color: var(--ink-muted) }
.jump { display: inline-block; margin-top: 8px; font-size: 12px; font-weight: 500 }
/* The tile keeps its own surface; the link only carries the affordance. */
.tilelink { display: block; border-radius: var(--radius-card); color: inherit }
.tilelink:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }

.demo { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--hairline); width: 100% }
.demo__label {
  margin: 0 0 8px; font-size: 10px; font-weight: 700; letter-spacing: .09em;
  text-transform: uppercase; color: var(--ink-muted);
}
.demo__buttons { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center }
.demo__note { margin: 8px 0 0; font-size: 11px; color: var(--ink-muted) }

.stack { display: flex; flex-direction: column; gap: 14px; min-width: 0 }

.facts { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)) }
@media (min-width: 640px) { .facts { grid-template-columns: repeat(4, minmax(0, 1fr)) } }
.facts__primary { grid-column: span 2 }
.facts__hint { margin: 2px 0 0; font-size: 12px; color: var(--ink-muted) }

.sep { margin: 0 5px; color: var(--ink-muted) }

.incidents { list-style: none; margin: 6px 0 0; padding: 0 }
.incidents li + li { border-top: 1px solid var(--hairline) }
</style>
