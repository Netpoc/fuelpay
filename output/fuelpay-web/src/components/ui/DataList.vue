<script setup lang="ts">
/**
 * Label/value pairs on a CSS grid.
 *
 * Replaces antd's `Descriptions bordered`, which renders a real <table> and is
 * the classic horizontal-overflow case on a phone once values get long.
 */
withDefaults(defineProps<{ dense?: boolean }>(), { dense: false })
</script>

<template>
  <dl class="dl" :class="{ 'dl--dense': dense }"><slot /></dl>
</template>

<style scoped>
.dl {
  display: grid; gap: 1px; margin: 0;
  grid-template-columns: 1fr;
  background: var(--hairline);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-control);
  overflow: hidden;
}
@media (min-width: 640px) { .dl { grid-template-columns: repeat(2, 1fr) } }
@media (min-width: 1280px) { .dl { grid-template-columns: repeat(3, 1fr) } }
.dl--dense { grid-template-columns: repeat(2, 1fr) !important; }
</style>
