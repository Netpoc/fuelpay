<script setup lang="ts">
/**
 * A number. Always tabular, so a value ticking 998 -> 1002 does not make its
 * own label jitter, and slashed-zero so 0 and O never trade places in a serial.
 */
withDefaults(defineProps<{ value: string | number; unit?: string; size?: 'sm' | 'md' | 'lg' | 'xl' }>(), {
  size: 'md',
})
const SIZE = { sm: 'text-xs', md: 'text-sm', lg: 'text-lg', xl: 'text-[30px] leading-[34px]' }
</script>

<template>
  <span class="tabular" :class="SIZE[size]"
    ><slot>{{ value }}</slot
    ><span v-if="unit" class="unit">{{ unit }}</span></span
  >
</template>

<style scoped>
.unit {
  margin-left: 0.22em;
  font-size: 0.72em;
  color: var(--ink-muted);
  font-weight: 500;
}
</style>
