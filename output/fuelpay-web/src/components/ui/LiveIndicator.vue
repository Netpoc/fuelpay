<script setup lang="ts">
/**
 * Data freshness — deliberately NOT connection state.
 *
 * There is no live stream yet, so this reports how old the newest reading is.
 * Saying "Live" would imply a socket that does not exist. When SSE lands this
 * is where it plugs in.
 */
import { computed } from 'vue'
import { useIntervalFn } from '@vueuse/core'
import { ref } from 'vue'
import { relativeTime, secondsSince } from '@/lib/format'

const props = defineProps<{ updatedAt: number | null; error?: string | null }>()

const now = ref(Date.now())
useIntervalFn(() => (now.value = Date.now()), 15_000)

const state = computed(() => {
  if (props.error) return 'error'
  if (!props.updatedAt) return 'idle'
  // One simulated tick is 5 minutes; past ~2 ticks the data is stale.
  return secondsSince(new Date(props.updatedAt).toISOString(), now.value) > 660 ? 'stale' : 'fresh'
})

const text = computed(() => {
  if (props.error) return 'Disconnected'
  if (!props.updatedAt) return 'Loading…'
  return relativeTime(new Date(props.updatedAt).toISOString(), now.value)
})
</script>

<template>
  <span class="live" :class="`live--${state}`" aria-live="polite">
    <span class="dot" aria-hidden="true" />
    <span class="txt">{{ text }}</span>
  </span>
</template>

<style scoped>
.live { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; color: var(--ink-muted) }
.dot { width: 7px; height: 7px; border-radius: 999px; background: var(--ink-subtle); flex: none }
.live--fresh .dot { background: var(--status-ok); animation: breathe 2.6s ease-in-out infinite }
.live--stale .dot { background: var(--status-watch) }
.live--error .dot { background: var(--status-critical) }
@keyframes breathe { 50% { opacity: .35 } }
@media (max-width: 400px) { .txt { display: none } }
</style>
