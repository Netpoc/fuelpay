<script setup lang="ts">
import { useRoute } from 'vue-router'
import { RouterLink } from 'vue-router'
import { Button } from 'ant-design-vue'
import BrandBackdrop from '@/components/brand/BrandBackdrop.vue'
import NsibidiGlossary from '@/components/brand/NsibidiGlossary.vue'

const route = useRoute()

/**
 * The mark, drained. The logo normally says "you have fuel"; here it says
 * there is nothing at this address.
 */
const DROP = 'M16 3 L8.12 14.69 A9.5 9.5 0 1 0 23.88 14.69 Z'
</script>

<template>
  <div class="page">
    <section class="stage">
      <BrandBackdrop :nsibidi="0.08" ankara="band" band-side="bottom" />
      <div class="card glass-strong reveal">
        <svg width="84" height="84" viewBox="0 0 32 32" role="img" aria-label="Empty tank" class="mark">
          <defs><clipPath id="nf-fill"><rect x="0" y="28.4" width="32" height="3.6" /></clipPath></defs>
          <path :d="DROP" fill="currentColor" fill-opacity="0.06" />
          <path :d="DROP" fill="var(--np-coral)" fill-opacity="0.7" clip-path="url(#nf-fill)" />
          <path :d="DROP" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" />
        </svg>

        <p class="pill pill--night">404 · Tank empty</p>
        <h1>That page isn't on the <span class="text-ankara">network</span>.</h1>
        <p class="path mono">{{ route.fullPath }}</p>
        <p class="hint">It may have been renamed, or the generator may no longer be in the fleet.</p>

        <div class="actions">
          <RouterLink to="/fleet"><Button type="primary" size="large">Go to fleet</Button></RouterLink>
          <RouterLink to="/incidents"><Button size="large" ghost>View incidents</Button></RouterLink>
        </div>
      </div>
    </section>
    <NsibidiGlossary class="gloss" />
  </div>
</template>

<style scoped>
.page { max-width: 46rem; margin: 0 auto; padding: 32px 16px 24px }
/* Night stage in both themes — a brand moment, like the sign-in panel. */
.stage {
  position: relative; isolation: isolate; overflow: hidden;
  display: grid; place-items: center;
  padding: 48px 18px 84px;
  border-radius: var(--radius-panel);
  background: var(--np-night);
  color: var(--np-ivory);
}
.stage > :deep(.backdrop) { z-index: -1 }
.card {
  width: 100%; max-width: 30rem; text-align: center;
  padding: 32px 24px;
  border-radius: var(--radius-panel);
  /* Pin the glass to its night values: the stage is night in both themes. */
  background: rgb(20 18 43 / 72%);
  border-color: rgb(245 242 234 / 13%);
}
.mark { margin: 0 auto 16px; color: var(--np-mist) }
.pill--night { color: var(--np-mist); border-color: rgb(245 242 234 / 16%); background: rgb(245 242 234 / 5%); margin: 0 0 14px }
h1 { margin: 0; font-size: clamp(24px, 4vw, 32px); font-weight: 800; letter-spacing: -0.03em; line-height: 1.08 }
.path {
  margin: 12px auto 0; font-size: 12px; color: var(--np-mist);
  overflow-wrap: anywhere; max-width: 32ch;
}
.hint { margin: 10px auto 0; font-size: 13.5px; color: var(--np-mist); max-width: 42ch }
.actions { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 24px }
/* The night stage needs the dark-theme primary regardless of the app theme. */
.actions :deep(.ant-btn-primary),
.actions :deep(.ant-btn-primary:not(:disabled):hover) { background: var(--np-saffron); color: var(--np-void); border-color: var(--np-saffron) }
.actions :deep(.ant-btn-primary:not(:disabled):hover) { filter: brightness(1.08) }
.actions :deep(.ant-btn-background-ghost) { color: var(--np-ivory); border-color: rgb(245 242 234 / 35%) }
.gloss { margin-top: 18px; padding: 0 4px }
</style>
