<script setup lang="ts">
/**
 * One site in the rail — and the keyboard/screen-reader equivalent of its pin.
 *
 * markercluster removes clustered markers from the DOM, so at national zoom
 * some sites are neither visible nor tabbable on the map itself. This list is
 * the only complete path to every site, which is why it carries the same
 * sentence the pin does rather than an abbreviated version.
 */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import { STATE_LABEL } from '@/components/tank/state'
import { EVENT_SPEC } from '@/lib/incidents'
import { litres, percent } from '@/lib/format'
import { pinView } from './pin'
import type { SiteMapRow } from '@/stores/sites'

const props = defineProps<{ row: SiteMapRow; selected: boolean }>()
const emit = defineEmits<{ select: [siteId: string] }>()

const view = computed(() => pinView(props.row, props.selected))
const worst = computed(() => props.row.alerts[0])
</script>

<template>
  <li class="item" :class="{ 'item--selected': selected }">
    <button
      type="button"
      class="hit"
      :aria-pressed="selected"
      :aria-label="view.ariaLabel"
      @click="emit('select', row.site.id)"
    >
      <span
        class="glyph"
        :class="[`glyph--${view.weight}`, { 'glyph--unknown': view.unknown }]"
        :data-state="view.state ?? 'none'"
        aria-hidden="true"
        >{{ view.label }}</span
      >

      <span class="body">
        <span class="name">{{ row.site.name }}</span>
        <span class="meta">
          <!-- Never hue alone: the state is written out here every time. -->
          <template v-if="row.darkSensors">
            {{ row.darkSensors }} sensor{{ row.darkSensors === 1 ? '' : 's' }} dark
          </template>
          <template v-else-if="row.state">{{ STATE_LABEL[row.state] }}</template>
          <template v-else>No signal</template>
          <template v-if="row.summary?.bulk_capacity_l">
            · {{ litres(row.summary.bulk_level_l) }}
          </template>
          <template v-else-if="row.bulk"> · {{ percent(row.bulk.levelPct) }}</template>
        </span>
      </span>

      <span v-if="worst" class="badge" :data-status="EVENT_SPEC[worst.event_type].status">
        {{ EVENT_SPEC[worst.event_type].glyph }}
        <span class="sr-only">{{ EVENT_SPEC[worst.event_type].label }}</span>
      </span>
    </button>

    <RouterLink class="open" :to="{ name: 'site', params: { id: row.site.id } }">
      <span class="sr-only">Open {{ row.site.name }}</span>
      <span aria-hidden="true">›</span>
    </RouterLink>
  </li>
</template>

<style scoped>
.item {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid var(--hairline);
}
.item--selected { background: var(--surface-sunken); }

.hit {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
  padding: 9px 4px 9px 12px;
  background: none;
  border: 0;
  text-align: left;
  cursor: pointer;
  color: inherit;
  font: inherit;
}
.hit:hover { background: var(--surface-sunken); }

.glyph {
  --c: var(--status-ok);
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.glyph[data-state='ok'] { --c: var(--status-ok); --t: var(--status-ok-text); }
.glyph[data-state='watch'],
.glyph[data-state='low'] { --c: var(--status-watch); --t: var(--status-watch-text); }
.glyph[data-state='critical'] { --c: var(--status-critical); --t: var(--status-critical-text); }

.glyph--soft {
  background: color-mix(in srgb, var(--c) 18%, var(--surface-raised));
  color: var(--t);
  box-shadow: inset 0 0 0 1.5px var(--c);
}
.glyph--solid { background: var(--c); color: var(--on-solid); }
.glyph--unknown {
  background: var(--surface-raised);
  color: var(--ink-muted);
  border: 1.5px dashed var(--hairline-strong);
  box-shadow: none;
}

.body { display: flex; flex-direction: column; min-width: 0; }
.name {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.meta { font-size: 11px; color: var(--ink-muted); }

.badge {
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: 999px;
  font-size: 9px;
  color: var(--on-solid);
}
.badge[data-status='critical'] { background: var(--status-critical); }
.badge[data-status='watch'] { background: var(--status-watch); }

.open {
  display: grid;
  place-items: center;
  padding: 0 10px;
  color: var(--ink-subtle);
  font-size: 16px;
}
.open:hover { color: var(--interactive); background: var(--surface-sunken); }

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
</style>
