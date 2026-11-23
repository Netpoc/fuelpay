<script setup lang="ts">
/**
 * A site's bulk reserve — the tier that feeds every generator on site.
 *
 * Two things this deliberately refuses to smooth over:
 *
 * 1. A total summed over a partial set is labelled as such. If one of two bulk
 *    sensors is dark, the site looks half empty, and an unlabelled number would
 *    send someone to a site that is fine.
 * 2. A tank with no signal shows a dash and its sensor state, never a last
 *    known level. Carrying a stale number forward is how fuel goes missing
 *    without anyone noticing.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import AppCard from '@/components/ui/AppCard.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import Figure from '@/components/ui/Figure.vue'
import FuelTank from '@/components/tank/FuelTank.vue'
import { STATE_LABEL } from '@/components/tank/state'
import { litres, percent, relativeTime } from '@/lib/format'
import type { SiteBulk } from '@/stores/fleet'
import type { Incident } from '@/lib/incidents'
import { EVENT_SPEC } from '@/lib/incidents'

const props = defineProps<{ bulk: SiteBulk; alerts?: Incident[] }>()

const alerts = computed(() => props.alerts ?? [])

const SENSOR_LABEL = {
  ONLINE: 'Live',
  STALE: 'Delayed',
  OFFLINE: 'No signal',
} as const

const sensorTone = (status: 'ONLINE' | 'STALE' | 'OFFLINE') =>
  status === 'ONLINE' ? 'ok' : status === 'STALE' ? 'watch' : 'critical'

/**
 * The headline status — but only when it can honestly be claimed.
 *
 * A fill-derived state computed over a partial set is wrong in the dangerous
 * direction: a site with one of two sensors dark reads as 24% and gets chipped
 * "Below reorder" while actually sitting near 70%. That is precisely the
 * false callout the partial-total banner exists to prevent, so the chip must
 * not assert a level state it cannot stand behind.
 */
const headline = computed(() => {
  if (props.bulk.levelL === undefined) return { state: 'watch' as const, label: 'No signal' }
  if (props.bulk.partial) return { state: 'watch' as const, label: 'Partial data' }
  return { state: props.bulk.state, label: STATE_LABEL[props.bulk.state] }
})

/**
 * The worst live alert on a given tank, in the shape FuelTank draws.
 *
 * A short delivery and an unverified loss are both fuel leaving the tank
 * unaccounted for, so they take the drain marker rather than being dropped for
 * not being literal theft.
 */
const alertFor = (tankId: string) => {
  const worst = alerts.value.find((incident) => incident.tank_id === tankId)
  if (!worst) return null
  return ['SUSPECTED_DRAIN', 'SHORT_DELIVERY', 'UNVERIFIED_LOSS'].includes(worst.event_type)
    ? 'drain'
    : 'low'
}
</script>

<template>
  <AppCard class="bulk" padding="none">
    <header class="bulk__head">
      <div class="bulk__id">
        <p class="bulk__site">{{ bulk.site.name }}</p>
        <p class="bulk__sub">
          Bulk storage · {{ bulk.total }} tank{{ bulk.total === 1 ? '' : 's' }}
        </p>
      </div>
      <StatusChip :state="headline.state" :label="headline.label" size="sm" />
    </header>

    <div class="bulk__body">
      <!-- One vessel per physical tank, beside the roll-up. A site with two
           bulk tanks half-full each is a different situation from one full and
           one empty, and a single summed bar cannot show that. -->
      <div class="bulk__vessels">
        <RouterLink
          v-for="tank in bulk.tanks"
          :key="tank.id"
          :to="{ name: 'tank', params: { id: tank.id } }"
          class="vessel"
          :aria-label="`Open ${tank.name}`"
        >
          <FuelTank
            kind="BULK"
            size="sm"
            :level-l="tank.level_l ?? 0"
            :capacity-l="tank.capacity_l"
            :reorder-threshold-pct="tank.reorder_threshold_pct"
            :unknown="tank.level_l === null"
            :alert="alertFor(tank.id)"
          />
        </RouterLink>
      </div>

      <div class="bulk__figure">
        <Figure :value="bulk.levelPct !== undefined ? percent(bulk.levelPct, 0) : '—'" size="lg" />
        <p class="bulk__litres">
          {{ bulk.levelL !== undefined ? litres(bulk.levelL) : 'no signal' }}
          <span class="bulk__of">of {{ litres(bulk.capacityL) }}</span>
        </p>
      </div>

      <div
        v-if="bulk.levelPct !== undefined"
        class="bar"
        :class="`bar--${bulk.state}`"
        :style="{ '--fill': `${Math.min(100, bulk.levelPct)}%` }"
        role="presentation"
      />
    </div>

    <!-- Not a footnote: a total over a subset of tanks understates the site,
         and reading it as the whole reserve is a callout nobody needed. -->
    <p v-if="bulk.partial" class="bulk__partial">
      Total covers {{ bulk.reporting }} of {{ bulk.total }} tanks — the rest have no signal.
    </p>
    <p v-else-if="bulk.levelL === undefined" class="bulk__partial bulk__partial--hard">
      No bulk sensor on this site is reporting. Level unknown.
    </p>

    <ul v-if="alerts.length" class="bulk__alerts">
      <li v-for="alert in alerts" :key="alert.id">
        <StatusChip
          :state="EVENT_SPEC[alert.event_type].status"
          :label="EVENT_SPEC[alert.event_type].label"
          size="sm"
        />
      </li>
    </ul>

    <ul class="bulk__tanks">
      <li v-for="tank in bulk.tanks" :key="tank.id">
        <RouterLink :to="{ name: 'tank', params: { id: tank.id } }" class="tankrow">
          <span class="tankrow__name">{{ tank.name }}</span>
          <span class="tankrow__level">
            {{ tank.level_l !== null ? litres(tank.level_l) : '—' }}
          </span>
          <span
            class="tankrow__sensor"
            :class="`tankrow__sensor--${sensorTone(tank.sensor_status)}`"
          >
            {{ SENSOR_LABEL[tank.sensor_status] }}
            <template v-if="tank.measured_at && tank.sensor_status !== 'ONLINE'">
              · {{ relativeTime(tank.measured_at) }}
            </template>
          </span>
        </RouterLink>
      </li>
    </ul>
  </AppCard>
</template>

<style scoped>
.bulk { overflow: hidden }

.bulk__head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 10px;
  padding: 12px 14px 10px;
}
.bulk__site { margin: 0; font-size: 14px; font-weight: 650 }
.bulk__sub { margin: 2px 0 0; font-size: 11px; color: var(--ink-muted) }

.bulk__body { padding: 0 14px 12px }
.bulk__vessels {
  display: flex; align-items: flex-end; justify-content: center;
  gap: 14px; margin: 2px 0 12px;
}
.bulk__figure { display: flex; align-items: baseline; gap: 10px }
.bulk__litres { margin: 0; font-size: 12px; color: var(--ink-muted) }
.bulk__of { opacity: .75 }

.bar {
  margin-top: 10px; height: 6px; border-radius: 999px;
  background: var(--surface-sunken); overflow: hidden; position: relative;
}
.bar::after {
  content: ''; position: absolute; inset: 0 auto 0 0; width: var(--fill);
  border-radius: 999px;
  transition: width var(--dur-level) var(--ease-decelerate);
  background: var(--status-ok);
}
.bar--watch::after, .bar--low::after { background: var(--status-watch) }
.bar--critical::after { background: var(--status-critical) }

.bulk__partial {
  margin: 0; padding: 8px 14px; font-size: 11px; line-height: 1.45;
  color: var(--status-watch-text);
  background: color-mix(in srgb, var(--status-watch) 10%, transparent);
  border-top: 1px solid var(--hairline);
}
.bulk__partial--hard {
  color: var(--status-critical-text);
  background: color-mix(in srgb, var(--status-critical) 10%, transparent);
}

.bulk__alerts {
  display: flex; flex-wrap: wrap; gap: 6px; margin: 0; padding: 10px 14px 0; list-style: none;
}

.bulk__tanks {
  margin: 10px 0 0; padding: 0; list-style: none;
  border-top: 1px solid var(--hairline);
}
.bulk__vessels .vessel { display: block; border-radius: var(--radius-card) }
.bulk__vessels .vessel:hover { background: var(--surface-sunken) }
.bulk__vessels .vessel:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px }

.tankrow {
  display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: baseline;
  padding: 7px 14px; font-size: 12px;
  color: inherit;
}
.tankrow:hover { background: var(--surface-sunken) }
.tankrow:hover .tankrow__name { color: var(--ink) }
.bulk__tanks li + li .tankrow { border-top: 1px solid var(--hairline) }
.tankrow__name { color: var(--ink-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.tankrow__level { font-variant-numeric: tabular-nums; font-weight: 600 }
.tankrow__sensor { font-size: 11px }
.tankrow__sensor--ok { color: var(--ink-muted) }
.tankrow__sensor--watch { color: var(--status-watch-text) }
.tankrow__sensor--critical { color: var(--status-critical-text) }
</style>
