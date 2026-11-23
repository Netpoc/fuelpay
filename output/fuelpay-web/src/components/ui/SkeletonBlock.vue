<script setup lang="ts">
/** Mirrors the real layout so the page does not reflow when data lands. */
withDefaults(defineProps<{ height?: string; radius?: string; width?: string }>(), {
  height: '1rem', radius: 'var(--radius-control)', width: '100%',
})
</script>

<template>
  <div class="sk" :style="{ height, borderRadius: radius, width }" aria-hidden="true" />
</template>

<style scoped>
.sk {
  background: linear-gradient(90deg, var(--surface-sunken) 25%,
    color-mix(in srgb, var(--hairline) 70%, var(--surface-sunken)) 37%, var(--surface-sunken) 63%);
  background-size: 400% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
}
@keyframes shimmer { from { background-position: 100% 0 } to { background-position: 0 0 } }
@media (prefers-reduced-motion: reduce) {
  .sk { animation: none; background: var(--surface-sunken) }
}
</style>
