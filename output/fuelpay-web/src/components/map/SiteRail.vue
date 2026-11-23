<script setup lang="ts">
/**
 * Everything the map cannot say, beside the map.
 *
 * Three tabs, so nothing the card dashboard did was lost when the map took the
 * page: Sites is the bulk rollup, Units is the generator list with its filters,
 * Incidents is the live feed.
 *
 * The Sites tab is also the map's accessible equivalent, which is why this rail
 * comes BEFORE the map in DOM order and is open by default on desktop. If it
 * defaulted collapsed, the only complete path to every site would be behind a
 * disclosure.
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import EmptyState from '@/components/ui/EmptyState.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import IncidentRow from '@/components/incidents/IncidentRow.vue'
import SiteListItem from './SiteListItem.vue'
import { useFleetStore } from '@/stores/fleet'
import { useIncidentsStore } from '@/stores/incidents'
import { STATE_LABEL } from '@/components/tank/state'
import { litres, percent } from '@/lib/format'
import type { SiteMapRow } from '@/stores/sites'

const props = defineProps<{ rows: SiteMapRow[]; selectedId: string | null }>()
const emit = defineEmits<{ select: [siteId: string] }>()

const fleet = useFleetStore()
const incidents = useIncidentsStore()

type Tab = 'sites' | 'units' | 'incidents'
const tab = ref<Tab>('sites')

type UnitFilter = 'all' | 'incidents' | 'running' | 'attention'
const unitFilter = ref<UnitFilter>('all')

const tabs = computed(() => [
  { label: `Sites ${props.rows.length}`, value: 'sites' },
  { label: `Units ${fleet.rows.length}`, value: 'units' },
  { label: `Incidents ${incidents.alertCount}`, value: 'incidents' },
])

const unitFilters = computed(() => [
  { label: `All ${fleet.rows.length}`, value: 'all' },
  { label: `Incidents ${incidents.alertsByGenerator.size}`, value: 'incidents' },
  { label: `Running ${fleet.rows.filter((row) => row.running).length}`, value: 'running' },
  { label: `Low ${fleet.needsAttention.length}`, value: 'attention' },
])

/** Worst first — a rail you scroll should open on the thing that needs you. */
const STATE_RANK = { critical: 0, low: 1, watch: 2, ok: 3 } as const
const orderedSites = computed(() =>
  [...props.rows].sort(
    (a, b) =>
      (b.alerts.length ? 1 : 0) - (a.alerts.length ? 1 : 0) ||
      (b.darkSensors ? 1 : 0) - (a.darkSensors ? 1 : 0) ||
      STATE_RANK[a.state ?? 'ok'] - STATE_RANK[b.state ?? 'ok'] ||
      a.site.name.localeCompare(b.site.name),
  ),
)

const visibleUnits = computed(() =>
  fleet.rows.filter((row) => {
    if (unitFilter.value === 'incidents') return incidents.alertsByGenerator.has(row.generator.id)
    if (unitFilter.value === 'running') return row.running
    if (unitFilter.value === 'attention') return row.state === 'low' || row.state === 'critical'
    return true
  }),
)

const siteName = (siteId: string | null | undefined) =>
  siteId ? fleet.sites.get(siteId)?.name : undefined
</script>

<template>
  <aside class="rail" aria-label="Fleet detail">
    <div class="rail__tabs">
      <SegmentedControl
        :model-value="tab"
        :options="tabs"
        aria-label="Rail section"
        @update:model-value="tab = $event as Tab"
      />
    </div>

    <!-- Sites: the map's accessible equivalent. A real list of real links. -->
    <nav v-show="tab === 'sites'" class="rail__body" aria-label="Sites">
      <ul class="list">
        <SiteListItem
          v-for="row in orderedSites"
          :key="row.site.id"
          :row="row"
          :selected="row.site.id === selectedId"
          @select="emit('select', $event)"
        />
      </ul>
    </nav>

    <div v-show="tab === 'units'" class="rail__body">
      <div class="rail__filters">
        <SegmentedControl
          :model-value="unitFilter"
          :options="unitFilters"
          aria-label="Filter generators"
          @update:model-value="unitFilter = $event as UnitFilter"
        />
      </div>
      <EmptyState
        v-if="!visibleUnits.length"
        title="Nothing matches this filter."
        description="Switch back to All."
      />
      <ul v-else class="list">
        <li v-for="row in visibleUnits" :key="row.generator.id" class="unit">
          <RouterLink
            class="unit__link"
            :to="{ name: 'generator', params: { id: row.generator.id } }"
          >
            <span class="unit__pct tabular" :data-state="row.state">
              {{ percent(row.fuelPct ?? 0, 0) }}
            </span>
            <span class="unit__body">
              <span class="unit__name">{{ row.generator.name }}</span>
              <span class="unit__meta">
                {{ row.site?.name }} ·
                {{ row.running ? 'Running' : 'Stopped' }} ·
                {{ STATE_LABEL[row.state] }}
              </span>
            </span>
            <span class="unit__vol tabular">{{ litres(row.reading?.fuel_level_l) }}</span>
          </RouterLink>
        </li>
      </ul>
    </div>

    <div v-show="tab === 'incidents'" class="rail__body">
      <EmptyState
        v-if="!incidents.alerting.length"
        title="Nothing is alerting."
        description="Drains, short deliveries and dark sensors show up here."
      />
      <ul v-else class="list list--pad">
        <li v-for="incident in incidents.alerting" :key="incident.id">
          <IncidentRow
            :incident="incident"
            :generator-name="
              incident.generator_id
                ? fleet.byId.get(incident.generator_id)?.generator.name
                : undefined
            "
            :site-name="
              siteName(
                incident.tank_id
                  ? fleet.tanks.find((tank) => tank.id === incident.tank_id)?.site_id
                  : fleet.byId.get(incident.generator_id ?? '')?.generator.site_id,
              )
            "
          />
        </li>
      </ul>
    </div>
  </aside>
</template>

<style scoped>
.rail {
  display: flex;
  flex-direction: column;
  min-height: 0;
  min-width: 0;
  background: var(--surface-raised);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-panel);
  overflow: hidden;
}

.rail__tabs { padding: 10px; border-bottom: 1px solid var(--hairline); }
.rail__filters { padding: 10px; border-bottom: 1px solid var(--hairline); }

.rail__body { overflow-y: auto; min-height: 0; flex: 1; }

.list { list-style: none; margin: 0; padding: 0; }
.list--pad > li { padding: 4px 12px; border-bottom: 1px solid var(--hairline); }

.unit { border-bottom: 1px solid var(--hairline); }
.unit__link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  color: inherit;
}
.unit__link:hover { background: var(--surface-sunken); }

.unit__pct { flex: 0 0 auto; width: 38px; font-weight: 700; font-size: 13px; }
.unit__pct[data-state='ok'] { color: var(--status-ok-text); }
.unit__pct[data-state='watch'],
.unit__pct[data-state='low'] { color: var(--status-watch-text); }
.unit__pct[data-state='critical'] { color: var(--status-critical-text); }

.unit__body { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.unit__name {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.unit__meta { font-size: 11px; color: var(--ink-muted); }
.unit__vol { flex: 0 0 auto; font-size: 11px; color: var(--ink-muted); }
</style>
