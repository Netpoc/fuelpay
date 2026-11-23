<script setup lang="ts">
/** Tri-state: auto is a real answer, not the absence of one. */
import { computed } from 'vue'
import { useTheme } from '@/composables/useTheme'

const { preference, resolved, cycle } = useTheme()
const label = computed(() =>
  preference.value === 'auto' ? `Theme: system (${resolved.value})` : `Theme: ${preference.value}`,
)
</script>

<template>
  <button class="toggle" type="button" :title="label" :aria-label="label" @click="cycle">
    <svg v-if="preference === 'auto'" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">
      <circle cx="12" cy="12" r="8" /><path d="M12 4v16" /><path d="M12 4a8 8 0 0 1 0 16" fill="currentColor" stroke="none" />
    </svg>
    <svg v-else-if="preference === 'light'" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">
      <circle cx="12" cy="12" r="4.2" />
      <path d="M12 2.6v2.2M12 19.2v2.2M2.6 12h2.2M19.2 12h2.2M5.4 5.4l1.6 1.6M17 17l1.6 1.6M18.6 5.4L17 7M7 17l-1.6 1.6" />
    </svg>
    <svg v-else width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round">
      <path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z" />
    </svg>
  </button>
</template>

<style scoped>
.toggle {
  display: inline-flex; align-items: center; justify-content: center;
  width: 36px; height: 36px; border-radius: 999px;
  background: transparent; color: var(--ink-muted);
  border: 1px solid transparent; cursor: pointer;
  transition: background var(--dur-micro) var(--ease-standard), color var(--dur-micro) var(--ease-standard);
}
.toggle:hover { background: var(--surface-sunken); color: var(--ink); }
</style>
