<script setup lang="ts">
defineProps<{ label: string }>()
</script>

<template>
  <div class="item">
    <dt>{{ label }}</dt>
    <dd><slot /></dd>
  </div>
</template>

<style scoped>
.item { background: var(--surface-raised); padding: 10px 12px; min-width: 0; }
dt { font-size: 11px; letter-spacing: 0.05em; text-transform: uppercase; color: var(--ink-muted); }
dd { margin: 3px 0 0; font-size: 14px; overflow-wrap: anywhere; }
</style>
