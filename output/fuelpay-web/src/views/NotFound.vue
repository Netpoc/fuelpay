<script setup lang="ts">
import { useRoute } from 'vue-router'
import { RouterLink } from 'vue-router'
import { Button } from 'ant-design-vue'
import AppCard from '@/components/ui/AppCard.vue'

const route = useRoute()

/**
 * The mark, drained. The logo normally says "you have fuel"; here it says
 * there is nothing at this address.
 */
const DROP = 'M16 3 L8.12 14.69 A9.5 9.5 0 1 0 23.88 14.69 Z'
</script>

<template>
  <div class="page">
    <AppCard padding="lg" class="card">
      <svg width="78" height="78" viewBox="0 0 32 32" role="img" aria-label="Empty tank" class="mark">
        <defs><clipPath id="nf-fill"><rect x="0" y="28.4" width="32" height="3.6" /></clipPath></defs>
        <path :d="DROP" fill="currentColor" fill-opacity="0.05" />
        <path :d="DROP" fill="currentColor" fill-opacity="0.28" clip-path="url(#nf-fill)" />
        <path :d="DROP" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
      </svg>

      <h1>That page isn't on the network.</h1>
      <p class="path mono">{{ route.fullPath }}</p>
      <p class="hint">It may have been renamed, or the generator may no longer be in the fleet.</p>

      <div class="actions">
        <RouterLink to="/fleet"><Button type="primary">Go to fleet</Button></RouterLink>
        <RouterLink to="/incidents"><Button>View incidents</Button></RouterLink>
      </div>
    </AppCard>
  </div>
</template>

<style scoped>
.page { max-width: 34rem; margin: 0 auto; padding: 56px 16px }
.card { text-align: center }
.mark { margin: 0 auto 18px; color: var(--ink-muted) }
h1 { margin: 0; font-size: 21px; font-weight: 600; letter-spacing: -0.01em }
.path {
  margin: 10px auto 0; font-size: 12px; color: var(--ink-muted);
  overflow-wrap: anywhere; max-width: 32ch;
}
.hint { margin: 12px auto 0; font-size: 13px; color: var(--ink-muted); max-width: 42ch }
.actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 22px }
</style>
