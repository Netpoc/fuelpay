<script setup lang="ts">
/**
 * A headline figure. Replaces antd's Statistic, which cannot be restyled
 * (antd injects its CSS unlayered) and carried its colour through an inline
 * :value-style object.
 *
 * The roll-up animates only when a value CHANGES, never on mount — a dashboard
 * whose numbers all count up from zero on every load reads as a toy.
 */
import { computed, ref, watch } from 'vue'
import { useTransition, TransitionPresets, usePreferredReducedMotion } from '@vueuse/core'
import Figure from './Figure.vue'

const props = withDefaults(
  defineProps<{
    label: string
    value: number | null
    unit?: string
    sub?: string
    tone?: 'default' | 'ok' | 'watch' | 'critical'
    emphasis?: 'default' | 'primary'
    precision?: number
    animate?: boolean
    /**
     * Pre-formatted text to show instead of the number. For values whose unit
     * changes with magnitude — runtime is "45 min", "8.2 h" or "3 d" — where a
     * rolling numeric counter would be meaningless.
     */
    display?: string
  }>(),
  { tone: 'default', emphasis: 'default', precision: 0, animate: true },
)

const reduced = usePreferredReducedMotion()
const source = ref(props.value ?? 0)
const mounted = ref(false)

watch(
  () => props.value,
  (next) => {
    if (next === null) return
    if (!mounted.value || !props.animate || reduced.value === 'reduce') {
      source.value = next
      mounted.value = true
      return
    }
    source.value = next
  },
  { immediate: true },
)

const eased = useTransition(source, { duration: 600, transition: TransitionPresets.easeOutCubic })
const shown = computed(() => {
  if (props.display !== undefined) return props.display
  if (props.value === null) return '—'
  return eased.value.toFixed(props.precision).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
})
</script>

<template>
  <div class="tile" :class="[`tile--${tone}`, { 'tile--primary': emphasis === 'primary' }]">
    <p class="eyebrow">{{ label }}</p>
    <Figure :value="shown" :unit="unit" :size="emphasis === 'primary' ? 'xl' : 'lg'" class="value" />
    <p v-if="sub" class="sub">{{ sub }}</p>
    <slot />
  </div>
</template>

<style scoped>
.tile {
  background: var(--surface-raised);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-card);
  padding: 14px 16px;
  min-width: 0;
}
.eyebrow {
  margin: 0 0 4px;
  font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  /* Deliberately NOT muted: at 11px muted grey was the app's most widespread
     contrast failure. */
  color: var(--ink);
  font-weight: 600;
}
.value { font-weight: 600; display: block; }
.sub { margin: 3px 0 0; font-size: 11px; color: var(--ink-muted); }
.tile--ok .value { color: var(--status-ok-text) }
.tile--watch .value { color: var(--status-watch-text) }
.tile--critical .value { color: var(--status-critical-text) }
.tile--primary { background: var(--surface-raised); }
</style>
