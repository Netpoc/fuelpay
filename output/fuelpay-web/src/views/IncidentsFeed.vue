<script setup lang="ts">
/**
 * The incident feed. Built from scratch — this route was a 9-line placeholder
 * that the header nav linked to.
 *
 * All the logic already existed in the incidents store; this is the surface
 * for it.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Alert, Button, Select } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeading from '@/components/ui/SectionHeading.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import AppLogo from '@/components/ui/AppLogo.vue'
import IncidentRow from '@/components/incidents/IncidentRow.vue'
import { useFleetStore } from '@/stores/fleet'
import { useIncidentsStore } from '@/stores/incidents'
import type { Incident } from '@/lib/incidents'
import { EVENT_SPEC } from '@/lib/incidents'
import type { EventType } from '@/api/types'

const route = useRoute()
const fleet = useFleetStore()
const incidents = useIncidentsStore()

const RANGES = [
  { label: '24h', value: 24 },
  { label: '7d', value: 168 },
  { label: '30d', value: 720 },
]
const hours = ref(72)
const type = ref<'all' | EventType>('all')
const generatorId = ref<string | undefined>(
  typeof route.query.generator === 'string' ? route.query.generator : undefined,
)

onMounted(() => {
  fleet.loadAll()
  incidents.load(hours.value)
})

const reload = () => incidents.load(hours.value)

const tankById = computed(() => new Map(fleet.tanks.map((tank) => [tank.id, tank])))

/**
 * What to call an incident's subject.
 *
 * Site-level incidents — a short delivery, a dark bulk sensor — carry no
 * generator, so labelling purely by generator left the highest-severity rows
 * in the feed with a blank name. Fall back to the tank, which every one of
 * them has.
 */
const nameOf = (incident: Incident) => {
  if (incident.generator_id) return fleet.byId.get(incident.generator_id)?.generator.name
  return incident.tank_id ? tankById.value.get(incident.tank_id)?.name : undefined
}

const siteOf = (incident: Incident) => {
  if (incident.generator_id) return fleet.byId.get(incident.generator_id)?.site?.name
  const siteId = incident.tank_id ? tankById.value.get(incident.tank_id)?.site_id : undefined
  return siteId ? fleet.sites.get(siteId)?.name : undefined
}

const filtered = computed(() =>
  incidents.incidents.filter((incident) => {
    if (generatorId.value && incident.generator_id !== generatorId.value) return false
    if (type.value !== 'all') return incident.event_type === type.value
    // "All types" means all *reportable* types, not literally everything.
    // Transfers, engine cycles and sensor recoveries are fetched because
    // `liveAlerts` needs them to resolve alerts — they are not here to be
    // read. Left in, they outnumber real incidents roughly ten to one and
    // push the deliveries and outages off the screen entirely.
    return EVENT_SPEC[incident.event_type].severity !== 'debug'
  }),
)

/** Grouped by day, because "when" is how anyone scans an incident log. */
const grouped = computed(() => {
  const groups = new Map<string, Incident[]>()
  const today = new Date().toDateString()
  const yesterday = new Date(Date.now() - 86_400_000).toDateString()

  for (const incident of filtered.value) {
    const day = new Date(incident.occurred_at).toDateString()
    const label = day === today ? 'Today' : day === yesterday ? 'Yesterday' : day
    const list = groups.get(label) ?? []
    list.push(incident)
    groups.set(label, list)
  }
  return [...groups.entries()]
})

const typeOptions = computed(() => [
  { label: 'All types', value: 'all' },
  // Ordered by what an operator cares about, not alphabetically. TRANSFER sits
  // last and is reachable only by selecting it: hidden from the default view
  // as routine plumbing, but still inspectable when someone wants the pump
  // history.
  ...(
    [
      'SUSPECTED_DRAIN',
      'SHORT_DELIVERY',
      'UNVERIFIED_LOSS',
      'LOW_FUEL',
      'SIGNAL_LOSS',
      'DELIVERY',
      'TRANSFER',
    ] as EventType[]
  ).map((t) => ({
    label: EVENT_SPEC[t].label,
    value: t,
  })),
])

const generatorOptions = computed(() => [
  { label: 'All generators', value: undefined },
  ...fleet.rows.map((row) => ({ label: row.generator.name, value: row.generator.id })),
])
</script>

<template>
  <div class="page">
    <PageHeader
      title="Incidents"
      :subtitle="`${incidents.alertCount} live · ${filtered.length} in this window`"
    >
      <template #actions>
        <Button v-if="incidents.alertCount" size="small" @click="incidents.alerting.forEach((i) => incidents.dismiss(i.id))">
          Acknowledge all
        </Button>
      </template>
    </PageHeader>

    <Alert v-if="incidents.error" type="error" :message="incidents.error" show-icon class="mb-4" />

    <div class="filters">
      <SegmentedControl
        v-model="hours"
        :options="RANGES"
        aria-label="Time range"
        @update:model-value="reload"
      />
      <Select v-model:value="type" :options="typeOptions" class="sel" />
      <Select v-model:value="generatorId" :options="generatorOptions" class="sel sel--wide" placeholder="All generators" />
    </div>

    <!-- What needs doing now, separated from the historical record. -->
    <AppCard v-if="incidents.alertCount" tone="critical" class="mb-4">
      <SectionHeading title="Needs attention now" :level="3" />
      <TransitionGroup tag="ul" name="ack" class="list">
        <li v-for="incident in incidents.alerting" :key="incident.id">
          <IncidentRow
            :incident="incident"
            :generator-name="nameOf(incident)"
            :site-name="siteOf(incident)"
          >
            <template #action>
              <Button size="small" type="text" @click="incidents.dismiss(incident.id)">
                Acknowledge
              </Button>
            </template>
          </IncidentRow>
        </li>
      </TransitionGroup>
    </AppCard>

    <div v-if="incidents.loading && !incidents.incidents.length" class="stack">
      <AppCard v-for="n in 3" :key="n">
        <SkeletonBlock height="16px" width="50%" />
        <SkeletonBlock height="12px" width="30%" class="mt-2" />
      </AppCard>
    </div>

    <AppCard v-else-if="!filtered.length">
      <EmptyState
        title="No incidents in this window."
        description="That is the good outcome — every tank stayed above its reorder line and nothing left one unaccounted for."
      >
        <template #icon><AppLogo variant="mark" :size="44" /></template>
      </EmptyState>
    </AppCard>

    <div v-else class="stack">
      <section v-for="[day, rows] in grouped" :key="day">
        <h2 class="day">{{ day }}</h2>
        <AppCard padding="sm">
          <ul class="list">
            <li v-for="incident in rows" :key="incident.id">
              <IncidentRow
                :incident="incident"
                :generator-name="nameOf(incident)"
                :site-name="siteOf(incident)"
              />
            </li>
          </ul>
        </AppCard>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 68rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 24px 24px 72px } }

.filters { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px }
.sel { min-width: 150px }
.sel--wide { min-width: 190px }

.stack { display: flex; flex-direction: column; gap: 18px }
.day {
  margin: 0 0 8px; font-size: 11px; font-weight: 700; letter-spacing: .08em;
  text-transform: uppercase; color: var(--ink-muted);
}
.list { list-style: none; margin: 0; padding: 0 }
.list li + li { border-top: 1px solid var(--hairline) }

.ack-leave-active { transition: opacity var(--dur-surface) var(--ease-accelerate), transform var(--dur-surface) var(--ease-accelerate) }
.ack-leave-to { opacity: 0; transform: translateX(14px) }
.ack-move { transition: transform var(--dur-surface) var(--ease-standard) }
</style>
