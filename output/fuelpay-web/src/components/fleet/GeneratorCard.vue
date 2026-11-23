<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import AppCard from '@/components/ui/AppCard.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import Figure from '@/components/ui/Figure.vue'
import FuelTank from '@/components/tank/FuelTank.vue'
import { STATE_LABEL } from '@/components/tank/state'
import type { FleetRow } from '@/stores/fleet'
import type { Incident } from '@/lib/incidents'
import { EVENT_SPEC } from '@/lib/incidents'
import { profileLabel, relativeTime, signedLitres } from '@/lib/format'

const props = withDefaults(defineProps<{ row: FleetRow; alerts?: Incident[] }>(), {
  alerts: () => [],
})

/** The worst live incident drives the banner, the tank badge and the border. */
const topAlert = computed(() => props.alerts[0] ?? null)
const tankAlert = computed<'drain' | 'low' | null>(() =>
  !topAlert.value ? null : topAlert.value.event_type === 'SUSPECTED_DRAIN' ? 'drain' : 'low',
)
const tone = computed(() =>
  !topAlert.value
    ? props.row.state === 'low' || props.row.state === 'critical'
      ? 'watch'
      : 'default'
    : topAlert.value.event_type === 'SUSPECTED_DRAIN'
      ? 'critical'
      : 'watch',
)
</script>

<template>
  <AppCard
    as="div"
    padding="none"
    :tone="tone"
    interactive
    class="wrap"
  >
    <RouterLink :to="{ name: 'generator', params: { id: row.generator.id } }" class="hit">
      <!-- A live incident gets a banner. The tank badge catches the eye; this
           says what happened without needing a click. -->
      <div v-if="topAlert" class="banner" :class="`banner--${tone}`">
        <span aria-hidden="true">{{ EVENT_SPEC[topAlert.event_type].glyph || '!' }}</span>
        <span class="font-semibold">{{ EVENT_SPEC[topAlert.event_type].label }}</span>
        <Figure v-if="topAlert.volume_l" :value="signedLitres(topAlert.volume_l)" size="sm" />
        <span class="ml-auto opacity-85">{{ relativeTime(topAlert.ended_at) }}</span>
      </div>

      <div class="body">
        <FuelTank
          v-if="row.reading"
          size="sm"
          :level-l="row.reading.fuel_level_l"
          :capacity-l="row.generator.tank_capacity_l"
          :reorder-threshold-pct="row.generator.reorder_threshold_pct"
          :engine-running="row.running"
          :alert="tankAlert"
        />
        <!-- An explicit gap, not a tank drawn at zero — those mean very
             different things. Same footprint so card heights stay equal. -->
        <div v-else class="nodata">no data</div>

        <div class="min-w-0 flex-1">
          <p class="name">{{ row.generator.name }}</p>
          <p class="site">{{ row.site?.name ?? '—' }}</p>

          <div class="chips">
            <StatusChip :state="row.state" :label="STATE_LABEL[row.state]" size="sm" />
            <span class="run" :class="{ 'run--on': row.running }">
              <span class="run__dot" aria-hidden="true" />{{ row.running ? 'Running' : 'Stopped' }}
            </span>
          </div>

          <dl class="facts">
            <div><dt>Rating</dt><dd><Figure :value="row.generator.kva_rating" unit="kVA" size="sm" /></dd></div>
            <div><dt>Reorder</dt><dd><Figure :value="row.generator.reorder_threshold_pct" unit="%" size="sm" /></dd></div>
          </dl>

          <p v-if="row.reading" class="foot">
            {{ relativeTime(row.reading.time) }} · {{ profileLabel(row.site?.profile ?? '') }}
          </p>
        </div>
      </div>
    </RouterLink>
  </AppCard>
</template>

<style scoped>
.wrap {
  overflow: hidden;
  /* Off-screen cards skip layout and paint, which matters once each owns an
     animated SVG. */
  content-visibility: auto;
  contain-intrinsic-size: 190px;
}
.hit { display: block; color: inherit }

.banner {
  display: flex; align-items: center; gap: 8px;
  padding: 7px 12px; font-size: 12px; color: var(--on-solid);
  background: var(--status-watch);
}
.banner--critical { background: var(--status-critical) }

.body { display: flex; align-items: flex-start; gap: 14px; padding: 14px 16px }

.nodata {
  flex: none; width: 92px; aspect-ratio: 296 / 372;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-control);
  background: var(--surface-sunken); color: var(--ink-muted); font-size: 11px;
}

.name { margin: 0; font-size: 14px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.site { margin: 2px 0 0; font-size: 12px; color: var(--ink-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }

.chips { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 9px }
.run { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--ink-muted) }
.run__dot { width: 6px; height: 6px; border-radius: 999px; background: var(--ink-subtle) }
.run--on .run__dot { background: var(--status-ok) }

.facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 10px; margin: 10px 0 0 }
.facts dt { display: inline; font-size: 11px; color: var(--ink-muted) }
.facts dd { display: inline; margin: 0 0 0 4px; font-weight: 600 }

.foot { margin: 9px 0 0; font-size: 11px; color: var(--ink-muted) }
</style>
