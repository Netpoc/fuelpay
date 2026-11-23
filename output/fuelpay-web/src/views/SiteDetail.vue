<script setup lang="ts">
/**
 * Everything that happens at one address.
 *
 * A site is the unit fuel is actually delivered to and the unit the map pins,
 * but until now it had no page — it existed only as a filter dropdown and a
 * subtitle. Nearly all of this is reuse: the bulk card, the generator cards and
 * the incident rows are the same components the fleet screens use, so a figure
 * here cannot disagree with the same figure there.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { Alert, Button } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeading from '@/components/ui/SectionHeading.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import StatTile from '@/components/ui/StatTile.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import BulkStorageCard from '@/components/fleet/BulkStorageCard.vue'
import GeneratorCard from '@/components/fleet/GeneratorCard.vue'
import IncidentRow from '@/components/incidents/IncidentRow.vue'
import FleetMap from '@/components/map/FleetMap.vue'
import SiteFlowChart from '@/components/charts/SiteFlowChart.vue'

import { getSiteFuel, getTankConsumption, listEvents } from '@/api/fleet'
import type { Event, SiteFuel, TankConsumption } from '@/api/types'
import { useFleetStore } from '@/stores/fleet'
import { useIncidentsStore } from '@/stores/incidents'
import { useSitesStore } from '@/stores/sites'
import { groupIncidents, FEED_EVENT_TYPES } from '@/lib/incidents'
import { siteFlowDays, siteFlowTotals } from '@/lib/siteFlow'
import { litres, percent, profileLabel } from '@/lib/format'
import { STATE_LABEL } from '@/components/tank/state'

const props = defineProps<{ id: string }>()

const fleet = useFleetStore()
const incidents = useIncidentsStore()
const sites = useSitesStore()

const fuel = ref<SiteFuel | null>(null)
const flows = ref<TankConsumption[]>([])
const events = ref<Event[]>([])
const cursor = ref<string | null>(null)
const loading = ref(true)
const flowLoading = ref(false)
const loadingMore = ref(false)
const error = ref<string | null>(null)

const days = ref<7 | 30 | 60>(30)
const dayOptions = [
  { label: '7d', value: 7 },
  { label: '30d', value: 30 },
  { label: '60d', value: 60 },
]

/**
 * Engine transitions and tank top-ups are excluded by default.
 *
 * They outnumber everything else by roughly twenty to one, so an unfiltered
 * feed is several hundred "Engine start / Engine stop" rows with the single
 * delivery and the single dark sensor lost somewhere inside it.
 */
type Feed = 'key' | 'all'
const feed = ref<Feed>('key')
const feedOptions = [
  { label: 'Key events', value: 'key' },
  { label: 'All activity', value: 'all' },
]

const row = computed(() => sites.byId.get(props.id) ?? null)
const site = computed(() => fuel.value?.site ?? row.value?.site ?? null)

const generators = computed(() =>
  fleet.rows.filter((generator) => generator.generator.site_id === props.id),
)

const flowDays = computed(() => siteFlowDays(flows.value))
const totals = computed(() => siteFlowTotals(flowDays.value))

const incidentRows = computed(() => groupIncidents(events.value))

/** Same rule as the pin: a quiet sensor outranks the level behind it. */
const headline = computed(() => {
  const current = row.value
  if (!current) return null
  if (current.darkSensors) {
    return {
      state: 'critical' as const,
      label: `${current.darkSensors} sensor${current.darkSensors === 1 ? '' : 's'} dark`,
    }
  }
  if (current.partial) return { state: 'watch' as const, label: 'Partial data' }
  if (!current.state) return { state: 'watch' as const, label: 'No signal' }
  return { state: current.state, label: STATE_LABEL[current.state] }
})

const feedTypes = () => (feed.value === 'key' ? FEED_EVENT_TYPES : undefined)

async function loadSite() {
  loading.value = true
  error.value = null
  try {
    const [siteFuel, page] = await Promise.all([
      getSiteFuel(props.id),
      // Server-side filtering, so `next_cursor` actually means something. The
      // tank page's client-side filter silently breaks its own pagination.
      listEvents({ site_id: props.id, limit: 100, event_type: feedTypes() }),
    ])
    fuel.value = siteFuel
    events.value = page.items
    cursor.value = page.next_cursor
    document.title = `${siteFuel.site.name} · FuelPay`
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load this site.'
  } finally {
    loading.value = false
  }
}

async function loadFeed() {
  try {
    const page = await listEvents({ site_id: props.id, limit: 100, event_type: feedTypes() })
    events.value = page.items
    cursor.value = page.next_cursor
  } catch {
    /* the page is already rendered; leave the existing feed in place */
  }
}

/** The slow one — one call per tank — so it gets its own loading state. */
async function loadFlows() {
  const current = fuel.value
  if (!current) return
  flowLoading.value = true
  try {
    const tanks = [...current.bulk, ...current.day]
    flows.value = await Promise.all(
      tanks.map((tank) => getTankConsumption(tank.id, days.value)),
    )
  } catch {
    flows.value = []
  } finally {
    flowLoading.value = false
  }
}

async function loadOlder() {
  if (!cursor.value) return
  loadingMore.value = true
  try {
    const page = await listEvents({
      site_id: props.id,
      limit: 100,
      before: cursor.value,
      event_type: feedTypes(),
    })
    events.value = [...events.value, ...page.items]
    cursor.value = page.next_cursor
  } finally {
    loadingMore.value = false
  }
}

onMounted(async () => {
  if (!fleet.loadedAt) fleet.loadAll()
  if (!incidents.events.length) incidents.load()
  if (!sites.loadedAt) sites.load()
  await loadSite()
  loadFlows()
})

watch(
  () => props.id,
  async () => {
    await loadSite()
    loadFlows()
  },
)

watch(days, loadFlows)
watch(feed, loadFeed)
</script>

<template>
  <div class="page">
    <PageHeader
      :title="site?.name ?? 'Site'"
      :subtitle="
        site ? `${profileLabel(site.profile)}${site.address ? ` · ${site.address}` : ''}` : undefined
      "
      back-to="/fleet"
      back-label="Fleet"
    >
      <template #actions>
        <StatusChip v-if="headline" :state="headline.state" :label="headline.label" />
      </template>
    </PageHeader>

    <Alert v-if="error" type="error" :message="error" class="mb-4" show-icon />

    <!-- Everything below describes a window that was not fully observed. Say so
         once, at the top, rather than qualifying every figure. -->
    <Alert
      v-else-if="row?.darkSensors"
      type="warning"
      class="mb-4"
      show-icon
      :message="`${row.darkSensors} sensor${row.darkSensors === 1 ? '' : 's'} at this site ${row.darkSensors === 1 ? 'is' : 'are'} not reporting`"
      description="Levels shown are the last measured, however old, and totals are summed over the tanks that did report. Treat them as a floor."
    />

    <div class="layout">
      <aside class="side">
        <AppCard padding="none" class="locator">
          <div class="locator__map">
            <FleetMap
              v-if="row"
              :rows="[row]"
              :cluster="false"
              :interactive="false"
              :fit-to="props.id"
              :zoom="13"
            />
            <SkeletonBlock v-else height="180px" />
          </div>
          <dl v-if="site" class="locator__facts">
            <div>
              <dt>Coordinates</dt>
              <dd class="tabular">{{ site.latitude.toFixed(5) }}, {{ site.longitude.toFixed(5) }}</dd>
            </div>
            <div v-if="site.address">
              <dt>Address</dt>
              <dd>{{ site.address }}</dd>
            </div>
          </dl>
        </AppCard>

        <BulkStorageCard
          v-if="row?.bulk"
          :bulk="row.bulk"
          :alerts="row.bulk.tanks.flatMap((tank) => incidents.alertsByTank.get(tank.id) ?? [])"
        />

        <AppCard v-if="fuel?.day.length" padding="none" class="daytanks">
          <p class="daytanks__title">Day tanks</p>
          <ul class="daytanks__list">
            <li v-for="tank in fuel.day" :key="tank.id">
              <RouterLink class="daytank" :to="{ name: 'tank', params: { id: tank.id } }">
                <span class="daytank__name">{{ tank.name }}</span>
                <span class="daytank__level tabular">
                  {{ tank.level_l === null ? '—' : litres(tank.level_l) }}
                </span>
                <span class="daytank__pct" :data-sensor="tank.sensor_status">
                  {{ tank.sensor_status === 'ONLINE' ? percent(tank.level_pct) : 'No signal' }}
                </span>
              </RouterLink>
            </li>
          </ul>
        </AppCard>
      </aside>

      <div class="main">
        <section class="tiles" aria-label="Site summary">
          <template v-if="row?.summary">
            <StatTile
              class="tiles__primary"
              label="Bulk reserve"
              :value="row.summary.bulk_level_l ?? 0"
              unit="L"
              emphasis="primary"
              :sub="`${percent(row.summary.bulk_level_pct)} of ${litres(row.summary.bulk_capacity_l)} · ${row.summary.bulk_tanks_reporting}/${row.summary.bulk_tanks_total} reporting`"
            />
            <StatTile
              label="Day tanks"
              :value="row.summary.day_level_l ?? 0"
              unit="L"
              :sub="`${percent(row.summary.day_level_pct)} of ${litres(row.summary.day_capacity_l)}`"
            />
            <StatTile
              label="Running"
              :value="row.summary.running_count"
              :sub="`of ${row.summary.generator_count} on site`"
            />
            <StatTile label="Burned 24h" :value="row.summary.consumed_l_24h" unit="L" />
            <StatTile
              label="Delivered 24h"
              :value="row.summary.delivered_l_24h"
              unit="L"
              :tone="row.summary.delivered_l_24h > 0 ? 'ok' : 'default'"
            />
            <StatTile
              label="Drained 24h"
              :value="row.summary.drained_l_24h"
              unit="L"
              :tone="row.summary.drained_l_24h > 0 ? 'critical' : 'default'"
              sub="suspected theft"
            />
            <StatTile
              v-if="row.summary.short_delivery_l_24h > 0"
              label="Short delivery 24h"
              :value="row.summary.short_delivery_l_24h"
              unit="L"
              tone="critical"
              sub="billed but not received"
            />
            <StatTile
              v-if="row.summary.unverified_loss_l_24h > 0"
              label="Unverified loss 24h"
              :value="row.summary.unverified_loss_l_24h"
              unit="L"
              tone="critical"
              sub="missing across an outage"
            />
          </template>
          <template v-else>
            <AppCard v-for="n in 6" :key="n" padding="sm" :class="n === 1 ? 'tiles__primary' : ''">
              <SkeletonBlock height="11px" width="60%" />
              <SkeletonBlock height="26px" class="mt-2" width="80%" />
            </AppCard>
          </template>
        </section>

        <SectionHeading title="Fuel flow" :hint="`last ${days} days`">
          <template #actions>
            <SegmentedControl
              :model-value="days"
              :options="dayOptions"
              aria-label="Chart range"
              @update:model-value="days = $event as 7 | 30 | 60"
            />
          </template>
        </SectionHeading>
        <AppCard class="chart-card">
          <SkeletonBlock v-if="flowLoading && !flowDays.length" height="260px" />
          <EmptyState
            v-else-if="!flowDays.length"
            title="No movement recorded."
            description="Nothing has been delivered, burned or lost in this window."
          />
          <template v-else>
            <SiteFlowChart :days="flowDays" />
            <p class="chart-note">
              Burned {{ litres(totals.consumed_l) }} · delivered
              {{ litres(totals.delivered_l) }} · transferred
              {{ litres(totals.transferred_l) }}
              <template v-if="totals.drained_l > 0">
                · drained <strong>{{ litres(totals.drained_l) }}</strong>
              </template>
              <template v-if="totals.unverified_loss_l > 0">
                · unverified <strong>{{ litres(totals.unverified_loss_l) }}</strong>
              </template>
              <template v-if="totals.unobservedDays">
                · {{ totals.unobservedDays }} day(s) with no readings, shown as gaps
              </template>
            </p>
          </template>
        </AppCard>

        <SectionHeading title="Generators" :hint="`${generators.length} on site`" />
        <section v-if="generators.length" class="gens">
          <GeneratorCard
            v-for="generator in generators"
            :key="generator.generator.id"
            :row="generator"
            :alerts="incidents.alertsByGenerator.get(generator.generator.id) ?? []"
          />
        </section>
        <EmptyState v-else title="No generators at this site." />

        <SectionHeading title="Activity" :hint="`${incidentRows.length} recent`">
          <template #actions>
            <SegmentedControl
              :model-value="feed"
              :options="feedOptions"
              aria-label="Activity filter"
              @update:model-value="feed = $event as Feed"
            />
          </template>
        </SectionHeading>
        <AppCard padding="none">
          <EmptyState
            v-if="!incidentRows.length && !loading"
            title="Nothing recorded here yet."
            description="Deliveries, transfers and incidents will appear as they happen."
          />
          <ul v-else class="feed">
            <li v-for="incident in incidentRows" :key="incident.id">
              <IncidentRow
                :incident="incident"
                :generator-name="
                  incident.generator_id
                    ? fleet.byId.get(incident.generator_id)?.generator.name
                    : undefined
                "
                :site-name="site?.name"
              />
            </li>
          </ul>
          <div v-if="cursor" class="feed__more">
            <Button :loading="loadingMore" @click="loadOlder">Load older</Button>
          </div>
        </AppCard>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 24px 24px 72px } }

.layout { display: grid; gap: 14px; grid-template-columns: minmax(0, 1fr) }
@media (min-width: 960px) {
  .layout { grid-template-columns: 320px minmax(0, 1fr); align-items: start }
}

.side { display: flex; flex-direction: column; gap: 12px; min-width: 0 }
.main { display: flex; flex-direction: column; gap: 12px; min-width: 0 }

.locator { overflow: hidden }
.locator__map { height: 180px }
.locator__facts { margin: 0; padding: 12px 14px; border-top: 1px solid var(--hairline) }
.locator__facts div + div { margin-top: 8px }
.locator__facts dt {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-subtle);
}
.locator__facts dd { margin: 2px 0 0; font-size: 12px }

.daytanks__title {
  margin: 0; padding: 11px 14px 9px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.08em; text-transform: uppercase; border-bottom: 1px solid var(--hairline);
}
.daytanks__list { list-style: none; margin: 0; padding: 0 }
.daytanks__list li + li { border-top: 1px solid var(--hairline) }
.daytank {
  display: grid; grid-template-columns: 1fr auto; gap: 2px 10px;
  padding: 9px 14px; color: inherit;
}
.daytank:hover { background: var(--surface-sunken) }
.daytank__name { font-size: 13px; font-weight: 600 }
.daytank__level { font-size: 13px; text-align: right }
.daytank__pct { grid-column: 1 / -1; font-size: 11px; color: var(--ink-muted) }
.daytank__pct[data-sensor='OFFLINE'] { color: var(--status-critical-text) }
.daytank__pct[data-sensor='STALE'] { color: var(--status-watch-text) }

.tiles { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)) }
@media (min-width: 768px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)) } }
.tiles__primary { grid-column: span 2 }

.chart-card { min-width: 0 }
.chart-note { margin: 8px 0 0; font-size: 11px; color: var(--ink-muted) }

.gens { display: grid; gap: 12px; grid-template-columns: minmax(0, 1fr) }
@media (min-width: 1280px) { .gens { grid-template-columns: repeat(2, minmax(0, 1fr)) } }

.feed { list-style: none; margin: 0; padding: 0 }
.feed > li { padding: 4px 14px; border-bottom: 1px solid var(--hairline) }
.feed__more { padding: 12px 14px; display: flex; justify-content: center }
</style>
