<script setup lang="ts">
/**
 * Not decoration.
 *
 * A StatusChip carries its own text label; a pin is a circle with a percentage
 * in it. This is the only place `watch` and `low` — which share a hue and are
 * separated by fill weight alone — get named, so without it the map conveys
 * part of its meaning by colour only.
 */
import { STATE_LABEL, type TankState } from '@/components/tank/state'
import { STATUS_WEIGHT } from '@/theme/tokens'

const STATES: TankState[] = ['ok', 'watch', 'low', 'critical']
</script>

<template>
  <div class="legend" role="group" aria-label="Map legend">
    <span v-for="state in STATES" :key="state" class="item">
      <span class="swatch" :class="`swatch--${STATUS_WEIGHT[state]}`" :data-state="state" />
      {{ STATE_LABEL[state] }}
    </span>
    <span class="item">
      <span class="swatch swatch--unknown" />
      Unverified
    </span>
    <span class="item">
      <span class="swatch swatch--alert" aria-hidden="true">▼</span>
      Live incident
    </span>
  </div>
</template>

<style scoped>
.legend {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 7px 10px;
  border: 1px solid var(--hairline);
  border-radius: var(--radius-control);
  background: color-mix(in srgb, var(--surface-raised) 92%, transparent);
  font-size: 11px;
  color: var(--ink-muted);
  overflow-x: auto;
  scrollbar-width: none;
}
.legend::-webkit-scrollbar { display: none; }

.item { display: inline-flex; align-items: center; gap: 5px; white-space: nowrap; }

.swatch {
  --c: var(--status-ok);
  width: 12px;
  height: 12px;
  border-radius: 999px;
  flex: 0 0 auto;
}
.swatch[data-state='ok'] { --c: var(--status-ok); }
.swatch[data-state='watch'],
.swatch[data-state='low'] { --c: var(--status-watch); }
.swatch[data-state='critical'] { --c: var(--status-critical); }

.swatch--soft {
  background: color-mix(in srgb, var(--c) 18%, var(--surface-raised));
  box-shadow: inset 0 0 0 1.5px var(--c);
}
.swatch--solid { background: var(--c); }
.swatch--unknown {
  background: var(--surface-raised);
  border: 1.5px dashed var(--hairline-strong);
}
.swatch--alert {
  display: grid;
  place-items: center;
  background: var(--status-critical);
  color: var(--on-solid);
  font-size: 7px;
}
</style>
