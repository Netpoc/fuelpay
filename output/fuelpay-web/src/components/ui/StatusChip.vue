<script setup lang="ts">
/**
 * Status, encoded three ways at once: hue, fill weight, and text.
 *
 * The weight is not decoration. A four-step traffic-light palette cannot pass
 * colourblind validation — `watch` and `low` are metamers under deuteranopia —
 * so they share a hue and are separated by soft-vs-solid fill. Remove the
 * weight or the label and the two become genuinely indistinguishable.
 */
import { computed } from 'vue'
import { STATUS_WEIGHT, type StatusKey } from '@/theme/tokens'

const props = withDefaults(defineProps<{ state: StatusKey; label: string; size?: 'sm' | 'md' }>(), {
  size: 'md',
})
const weight = computed(() => STATUS_WEIGHT[props.state])
</script>

<template>
  <span class="chip" :class="[`chip--${state}`, `chip--${weight}`, `chip--${size}`]">
    <slot>{{ label }}</slot>
  </span>
</template>

<style scoped>
.chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  border-radius: 999px;
  font-weight: 600;
  white-space: nowrap;
  line-height: 1.5;
}
.chip--sm { padding: 1px 8px; font-size: 11px; }
.chip--md { padding: 3px 10px; font-size: 12px; }

.chip--ok { --c: var(--status-ok); --t: var(--status-ok-text); }
.chip--watch { --c: var(--status-watch); --t: var(--status-watch-text); }
.chip--low { --c: var(--status-watch); --t: var(--status-watch-text); }
.chip--critical { --c: var(--status-critical); --t: var(--status-critical-text); }

.chip--soft {
  background: color-mix(in srgb, var(--c) 13%, transparent);
  color: var(--t);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--c) 42%, transparent);
}
.chip--solid {
  background: var(--c);
  /* Dark text on the solid chip in dark mode: white on the dark amber is only
     3.2:1. */
  color: var(--on-solid);
}
</style>
