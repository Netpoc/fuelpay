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
/* Brand strip: night-3 in both themes, like the gate panel. */
.banner {
  background: var(--np-night-3);
  color: var(--np-ivory);
  font-size: 13px;
  border-bottom: 1px solid rgb(245 242 234 / 8%);
}
.banner__inner {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px;
  max-width: 90rem; margin: 0 auto; padding: 7px 16px;
}
@media (min-width: 768px) { .banner__inner { padding: 7px 24px } }
.tag {
  padding: 2px 9px; border-radius: 999px;
  background: var(--np-saffron); color: var(--np-void);
  font-family: var(--font-mono); font-size: 10.5px; font-weight: 700;
  letter-spacing: 0.12em; text-transform: uppercase;
}
.org { font-weight: 700 }
.days { font-family: var(--font-mono); font-size: 12px; color: var(--np-mist) }
.days.urgent { color: var(--np-saffron); font-weight: 700 }
.gen { display: inline-flex; align-items: center; gap: 6px; color: var(--np-mist) }
.spin {
  width: 10px; height: 10px; border-radius: 50%;
  border: 2px solid var(--np-mist); border-top-color: transparent;
  animation: spin 0.9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg) } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none } }
.spacer { flex: 1 }
.add {
  color: var(--np-ivory); text-decoration: none; padding: 4px 12px;
  border: 1px solid rgb(245 242 234 / 28%); border-radius: 999px;
  font-weight: 600; font-size: 12.5px;
  transition: border-color var(--dur-micro) var(--ease-standard), color var(--dur-micro) var(--ease-standard),
    background var(--dur-micro) var(--ease-standard);
}
.add:hover { border-color: var(--np-saffron); color: var(--np-saffron); background: rgb(247 183 51 / 8%) }
</style>
