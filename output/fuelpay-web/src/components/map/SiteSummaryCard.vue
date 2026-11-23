<script setup lang="ts">
/**
 * A site's posture in one card.
 *
 * Written once and used in three places — inside the map popup, in the rail's
 * selected state, and at the top of the site page — so the figure a pin
 * promises is literally the same component the page opens with.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import Figure from '@/components/ui/Figure.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import { STATE_LABEL } from '@/components/tank/state'
import { EVENT_SPEC } from '@/lib/incidents'
import { litres, percent, profileLabel, relativeTime, signedLitres } from '@/lib/format'
import type { SiteMapRow } from '@/stores/sites'

const props = withDefaults(defineProps<{ row: SiteMapRow; compact?: boolean }>(), {
  compact: false,
})

const summary = computed(() => props.row.summary)

/**
 * What the status chip says.
 *
 * A quiet sensor takes precedence over the level, because the level behind it
 * is the last one measured and may be hours old. Reporting a confident "OK"
 * over a tank nobody can see is the failure this product exists to prevent.
 */
const headline = computed(() => {
  const row = props.row
  if (row.darkSensors) {
    return {
      state: 'critical' as const,
      label: `${row.darkSensors} sensor${row.darkSensors === 1 ? '' : 's'} dark`,
    }
  }
  if (row.partial) return { state: 'watch' as const, label: 'Partial data' }
  if (!row.state) return { state: 'watch' as const, label: 'No signal' }
  return { state: row.state, label: STATE_LABEL[row.state] }
})

const bulkPct = computed(() => summary.value?.bulk_level_pct ?? props.row.bulk?.levelPct ?? null)
const dayPct = computed(() => summary.value?.day_level_pct ?? null)

/** Only the losses that actually happened — an empty row of zeroes is noise. */
const losses = computed(() => {
  const s = summary.value
  if (!s) return []
  return [
    { key: 'drained', label: 'Drained', value: s.drained_l_24h },
    { key: 'short', label: 'Short delivery', value: s.short_delivery_l_24h },
    { key: 'unverified', label: 'Unverified loss', value: s.unverified_loss_l_24h },
  ].filter((entry) => entry.value > 0)
})

const alerts = computed(() => props.row.alerts.slice(0, 2))
</script>

<template>
  <div class="site" :class="{ 'site--compact': compact }">
    <header class="site__head">
      <div class="site__id">
        <p class="site__name">{{ row.site.name }}</p>
        <p class="site__meta">
          {{ profileLabel(row.site.profile) }}
          <template v-if="row.site.address"> · {{ row.site.address }}</template>
        </p>
      </div>
      <StatusChip :state="headline.state" :label="headline.label" size="sm" />
    </header>

    <!-- Bulk leads: it is the larger reserve by an order of magnitude and the
         tier a tanker actually fills. -->
    <div class="tier">
      <div class="tier__row">
        <span class="tier__label">Bulk reserve</span>
        <Figure
          :value="
            summary?.bulk_level_l !== null && summary?.bulk_level_l !== undefined
              ? litres(summary.bulk_level_l)
              : bulkPct !== null
                ? percent(bulkPct)
                : '—'
          "
          size="md"
          class="tier__value"
        />
      </div>
      <div class="bar" :style="{ '--fill': `${Math.min(100, bulkPct ?? 0)}%` }" role="presentation" />
      <p class="tier__sub">
        <template v-if="summary">
          {{ percent(bulkPct) }} of {{ litres(summary.bulk_capacity_l) }}
          <template v-if="summary.bulk_tanks_total">
            · {{ summary.bulk_tanks_reporting }}/{{ summary.bulk_tanks_total }} reporting
          </template>
        </template>
        <template v-else-if="row.bulk">
          {{ percent(bulkPct) }} of {{ litres(row.bulk.capacityL) }}
        </template>
        <template v-else>no bulk storage at this site</template>
      </p>
    </div>

    <div v-if="summary?.day_tanks_total" class="tier tier--minor">
      <div class="tier__row">
        <span class="tier__label">Day tanks</span>
        <Figure :value="litres(summary.day_level_l)" size="sm" class="tier__value" />
      </div>
      <p class="tier__sub">
        {{ percent(dayPct) }} of {{ litres(summary.day_capacity_l) }} ·
        {{ summary.day_tanks_reporting }}/{{ summary.day_tanks_total }} reporting
      </p>
    </div>

    <dl class="facts">
      <div class="fact">
        <dt>Generators</dt>
        <dd>
          <Figure :value="`${row.running}/${row.generators.length}`" size="sm" /> running
        </dd>
      </div>
      <div v-if="summary" class="fact">
        <dt>Burned 24h</dt>
        <dd><Figure :value="litres(summary.consumed_l_24h)" size="sm" /></dd>
      </div>
      <div v-if="summary && summary.delivered_l_24h > 0" class="fact">
        <dt>Delivered 24h</dt>
        <dd><Figure :value="litres(summary.delivered_l_24h)" size="sm" /></dd>
      </div>
      <!-- Three separate claims, never collapsed into one "loss" figure: an
           unverified loss is fuel missing across an outage nobody watched, and
           reporting it as theft would be an accusation the data cannot support. -->
      <div v-for="loss in losses" :key="loss.key" class="fact fact--loss">
        <dt>{{ loss.label }} 24h</dt>
        <dd><Figure :value="litres(loss.value)" size="sm" /></dd>
      </div>
    </dl>

    <ul v-if="alerts.length" class="alerts">
      <li v-for="alert in alerts" :key="alert.id" class="alert">
        <span class="alert__glyph" :data-status="EVENT_SPEC[alert.event_type].status">
          {{ EVENT_SPEC[alert.event_type].glyph }}
        </span>
        <span class="alert__label">{{ EVENT_SPEC[alert.event_type].label }}</span>
        <span v-if="alert.volume_l" class="alert__vol tabular">
          {{ signedLitres(alert.volume_l) }}
        </span>
        <span class="alert__when">{{ relativeTime(alert.ended_at) }}</span>
      </li>
    </ul>

    <RouterLink
      class="open"
      :to="{ name: 'site', params: { id: row.site.id } }"
      data-autofocus
    >
      Open site
      <span aria-hidden="true">→</span>
    </RouterLink>
  </div>
</template>

<style scoped>
.site {
  display: flex;
  flex-direction: column;
  gap: 10px;
  color: var(--ink);
}
.site--compact { gap: 8px; }

.site__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.site__name { margin: 0; font-size: 14px; font-weight: 650; line-height: 1.3; }
.site__meta { margin: 2px 0 0; font-size: 11px; color: var(--ink-muted); line-height: 1.4; }

.tier__row { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.tier__label { font-size: 11px; font-weight: 600; color: var(--ink-muted); }
.tier__value { font-weight: 650; }
.tier__sub { margin: 4px 0 0; font-size: 11px; color: var(--ink-muted); }
.tier--minor .tier__label { font-weight: 500; }

.bar {
  margin-top: 6px;
  height: 5px;
  border-radius: 999px;
  background: var(--surface-sunken);
  overflow: hidden;
  position: relative;
}
.bar::after {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: var(--fill);
  background: linear-gradient(90deg, var(--accent), var(--status-ok));
  border-radius: 999px;
  transition: width var(--dur-level) var(--ease-decelerate);
}

.facts {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 12px;
  margin: 2px 0 0;
  padding-top: 8px;
  border-top: 1px solid var(--hairline);
}
.fact dt { font-size: 10px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--ink-subtle); }
.fact dd { margin: 1px 0 0; font-size: 12px; }
.fact--loss dd { color: var(--status-critical-text); font-weight: 600; }

.alerts { list-style: none; margin: 0; padding: 8px 0 0; border-top: 1px solid var(--hairline); }
.alert { display: flex; align-items: center; gap: 6px; font-size: 11px; padding: 2px 0; }
.alert__glyph { font-size: 10px; line-height: 1; }
.alert__glyph[data-status='critical'] { color: var(--status-critical-text); }
.alert__glyph[data-status='watch'] { color: var(--status-watch-text); }
.alert__label { font-weight: 600; }
.alert__vol { color: var(--ink-muted); }
.alert__when { margin-left: auto; color: var(--ink-subtle); }

.open {
  margin-top: 2px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  align-self: flex-start;
  font-size: 12px;
  font-weight: 600;
  color: var(--interactive);
  border-radius: var(--radius-control);
}
.open:hover { text-decoration: underline; }
</style>
