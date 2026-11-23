<script setup lang="ts">
/**
 * A strip under the header on demo accounts: days left, and the way to add
 * more. Says "generating" while a backfill runs, so an empty chart reads as
 * "not yet" rather than "broken".
 */
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { RouterLink } from 'vue-router'

import { useDemoStore } from '@/stores/demo'

const demo = useDemoStore()
let stop: (() => void) | null = null
onMounted(() => (stop = demo.watch()))
onBeforeUnmount(() => stop?.())

const daysText = computed(() => {
  const days = demo.status?.days_left
  if (days === null || days === undefined) return ''
  return days === 1 ? 'Last day' : `${days} days left`
})
const urgent = computed(() => (demo.status?.days_left ?? 99) <= 2)
</script>

<template>
  <div v-if="demo.isDemo" class="banner" role="region" aria-label="Demo account">
    <div class="banner__inner">
      <span class="tag">Demo</span>
      <span class="org">{{ demo.status?.organisation.name }}</span>
      <span class="days" :class="{ urgent }">{{ daysText }}</span>
      <span v-if="demo.status?.generating" class="gen" role="status">
        <span class="spin" aria-hidden="true" /> Generating data…
      </span>
      <span class="spacer" />
      <RouterLink
        v-if="demo.canAddLocation"
        :to="{ name: 'demo', query: { add: 'location' } }"
        class="add"
        >+ Location</RouterLink
      >
      <RouterLink
        v-if="demo.canAddTractor"
        :to="{ name: 'demo', query: { add: 'tractor' } }"
        class="add"
        >+ Tractor</RouterLink
      >
    </div>
  </div>
</template>

<style scoped>
.banner { background: #0b2545; color: #e9eff6; font-size: 13px }
.banner__inner {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px;
  max-width: 90rem; margin: 0 auto; padding: 7px 16px;
}
@media (min-width: 768px) { .banner__inner { padding: 7px 24px } }
.tag {
  padding: 1px 7px; border-radius: 999px; background: #f2a93b; color: #0b2545;
  font-size: 11px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
}
.org { font-weight: 600 }
.days { color: #9aabbe }
.days.urgent { color: #f2a93b; font-weight: 600 }
.gen { display: inline-flex; align-items: center; gap: 6px; color: #9aabbe }
.spin {
  width: 10px; height: 10px; border-radius: 50%;
  border: 2px solid #9aabbe; border-top-color: transparent;
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg) } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none } }
.spacer { flex: 1 }
.add {
  color: #e9eff6; text-decoration: none; padding: 3px 10px;
  border: 1px solid rgba(233, 239, 246, 0.3); border-radius: var(--radius-control);
}
.add:hover { border-color: #f2a93b; color: #f2a93b }
</style>
