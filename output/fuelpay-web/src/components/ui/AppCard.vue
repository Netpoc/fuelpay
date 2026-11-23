<script setup lang="ts">
/**
 * The single raised surface in the product.
 *
 * Replaces four copy-pasted treatments (.tile, .panel, .card and the key
 * gate's box) that had drifted to different radii and two of which wrote #fff
 * literally rather than using the surface token.
 */
withDefaults(
  defineProps<{
    as?: string
    padding?: 'none' | 'sm' | 'md' | 'lg'
    tone?: 'default' | 'watch' | 'critical'
    interactive?: boolean
  }>(),
  { as: 'div', padding: 'md', tone: 'default', interactive: false },
)

const PAD = { none: '', sm: 'p-3', md: 'p-4 sm:p-5', lg: 'p-5 sm:p-6' }
</script>

<template>
  <component
    :is="as"
    class="card"
    :class="[PAD[padding], `card--${tone}`, { 'card--interactive': interactive }]"
  >
    <slot />
  </component>
</template>

<style scoped>
.card {
  background: var(--surface-raised);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-card);
  box-shadow: var(--elev-1);
  color: inherit;
}
/* A live incident outranks a merely low tank, so the two tones differ in
   weight as well as hue. */
.card--watch {
  border-color: color-mix(in srgb, var(--status-watch) 55%, var(--hairline));
}
.card--critical {
  border-color: var(--status-critical);
  box-shadow: 0 0 0 1px var(--status-critical);
}
.card--interactive {
  display: block;
  transition:
    box-shadow var(--dur-micro) var(--ease-standard),
    transform var(--dur-micro) var(--ease-standard);
}
.card--interactive:hover {
  box-shadow: var(--elev-2);
  transform: translateY(-1px);
}
.card--interactive:active {
  transform: translateY(0);
  transition-duration: 80ms;
}
</style>
