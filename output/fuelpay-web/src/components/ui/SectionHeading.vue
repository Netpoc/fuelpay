<script setup lang="ts">
withDefaults(defineProps<{ title: string; level?: 2 | 3; hint?: string }>(), { level: 2 })
</script>

<template>
  <div class="flex flex-wrap items-center justify-between gap-3">
    <component :is="`h${level}`" class="heading" :class="level === 2 ? 'text-base' : 'text-sm'">
      {{ title }}
      <span v-if="hint" class="hint">{{ hint }}</span>
    </component>
    <div class="flex items-center gap-2"><slot name="actions" /></div>
  </div>
</template>

<style scoped>
.heading { font-family: var(--font-display); font-weight: 700; letter-spacing: -0.015em; margin: 0; }
.hint { margin-left: 8px; font-family: var(--font-sans); font-weight: 400; font-size: 12px; letter-spacing: 0; color: var(--ink-muted); }
</style>
