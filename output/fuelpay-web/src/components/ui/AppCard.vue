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
  /* Netpoc glass, flattened: the sheen gradient sits over the solid raised
     surface instead of blurring what is behind it. Dashboards render dozens
     of cards over a plain field, where backdrop-filter costs frames and adds
     nothing. */
  background: var(--glass-bg), var(--surface-raised);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-card);
  box-shadow: var(--elev-1), var(--glass-inset);
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
    box-shadow var(--dur-surface) var(--ease-out-expo),
    border-color var(--dur-surface) var(--ease-out-expo),
    transform var(--dur-surface) var(--ease-out-expo);
}
.card--interactive:hover {
  border-color: color-mix(in srgb, var(--accent) 45%, var(--hairline));
  box-shadow:
    var(--elev-2),
    0 0 0 1px color-mix(in srgb, var(--accent) 22%, transparent);
  transform: translateY(-2px);
}
.card--interactive:active {
  transform: translateY(0);
  transition-duration: 80ms;
}
</style>
