<script setup lang="ts">
import { RouterLink } from 'vue-router'
defineProps<{ title: string; subtitle?: string; backTo?: string; backLabel?: string }>()
</script>

<template>
  <header class="hdr">
    <RouterLink v-if="backTo" :to="backTo" class="back">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M15 18l-6-6 6-6" />
      </svg>
      {{ backLabel ?? 'Back' }}
    </RouterLink>
    <div class="bar">
      <div class="min-w-0">
        <h1 class="title">{{ title }}</h1>
        <p v-if="subtitle" class="sub">{{ subtitle }}</p>
        <slot name="meta" />
      </div>
      <div class="actions"><slot name="actions" /></div>
    </div>
  </header>
</template>

<style scoped>
.hdr { margin-bottom: 20px }
.back {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 12px; color: var(--ink-muted); margin-bottom: 8px;
  min-height: 32px;
}
.back:hover { color: var(--ink) }
.bar { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 12px }
.title { margin: 0; font-size: 24px; line-height: 1.25; letter-spacing: -0.015em; font-weight: 600 }
.sub { margin: 4px 0 0; font-size: 13px; color: var(--ink-muted) }
.actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px }
</style>
