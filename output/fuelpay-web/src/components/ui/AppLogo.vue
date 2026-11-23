<script setup lang="ts">
/**
 * The level mark. Inline SVG rather than an <img> so it inherits currentColor
 * and needs no second request.
 *
 * Geometry, clear space and the small-size rule are documented in
 * output/fuelpay-brand/manual.html. The silhouette must stay continuous — the
 * droplet's character lives in the shoulders where the straight tangent lines
 * meet the body circle, and clipping the outline turns it into a funnel.
 */
import { computed, useId } from 'vue'

const props = withDefaults(
  defineProps<{ variant?: 'mark' | 'horizontal'; size?: number; reversed?: boolean }>(),
  { variant: 'horizontal', size: 28, reversed: false },
)

// Unique per instance: several marks on one page would otherwise all clip to
// whichever clipPath the document resolved first.
const uid = useId()
const clipId = computed(() => `lm-${uid}`)

/** Below 24px the fill line stops surviving, so thicken the stroke and lift
 *  the tint. Same construction, optically compensated — not a second drawing. */
const small = computed(() => props.size < 24)
const stroke = computed(() => (small.value ? 2.4 : 1.6))
const tint = computed(() => (small.value ? 0.13 : 0.07))
const line = computed(() => (props.reversed ? '#E9EFF6' : 'var(--brand, #0B2545)'))
const DROP = 'M16 3 L8.12 14.69 A9.5 9.5 0 1 0 23.88 14.69 Z'
</script>

<template>
  <span class="logo" :class="{ 'logo--horizontal': variant === 'horizontal' }">
    <svg :width="size" :height="size" viewBox="0 0 32 32" role="img" aria-label="FuelPay">
      <defs>
        <clipPath :id="clipId"><rect x="0" y="18.1" width="32" height="13.9" /></clipPath>
      </defs>
      <path :d="DROP" :fill="line" :fill-opacity="tint" />
      <path :d="DROP" fill="#F2A93B" :clip-path="`url(#${clipId})`" />
      <path :d="DROP" fill="none" :stroke="line" :stroke-width="stroke" stroke-linejoin="round" />
    </svg>
    <span v-if="variant === 'horizontal'" class="wordmark" :style="{ fontSize: `${size * 0.63}px` }">
      FuelPay
    </span>
  </span>
</template>

<style scoped>
.logo { display: inline-flex; align-items: center; }
/* Gap is half the mark width — the clear-space rule from the manual. */
.logo--horizontal { gap: 0.5em; }
.wordmark {
  font-weight: 600;
  letter-spacing: -0.012em;
  line-height: 1;
  color: currentColor;
}
</style>
