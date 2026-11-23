<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div class="empty">
    <div class="icon"><slot name="icon" /></div>
    <p class="title">{{ title }}</p>
    <p v-if="description" class="desc">{{ description }}</p>
    <div class="mt-4"><slot name="action" /></div>
  </div>
</template>

<style scoped>
.empty { padding: 40px 20px; text-align: center; }
.icon :deep(svg) { margin: 0 auto 14px; }
.title { margin: 0; font-family: var(--font-display); font-size: 18px; font-weight: 700; letter-spacing: -0.015em; }
.desc { margin: 6px auto 0; max-width: 44ch; font-size: 13px; color: var(--ink-muted); }
</style>
