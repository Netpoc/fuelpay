<script setup lang="ts">
/**
 * Replaces antd's Segmented, which does not wrap or scroll internally and so
 * overflows a phone as soon as it has four labels.
 *
 * Below sm this becomes a scroll-snapping rail, so any number of options fits
 * at any width.
 */
import { nextTick, ref, watch } from 'vue'

interface Option { label: string; value: string | number }
const props = defineProps<{ modelValue: string | number; options: Option[]; ariaLabel?: string }>()
const emit = defineEmits<{ 'update:modelValue': [string | number] }>()

const rail = ref<HTMLElement>()
watch(
  () => props.modelValue,
  async () => {
    await nextTick()
    rail.value
      ?.querySelector<HTMLElement>('[aria-checked="true"]')
      ?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' })
  },
)
</script>

<template>
  <div ref="rail" class="seg" role="radiogroup" :aria-label="ariaLabel">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      role="radio"
      :aria-checked="option.value === modelValue"
      class="seg__item"
      @click="emit('update:modelValue', option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<style scoped>
.seg {
  display: flex; gap: 2px; padding: 3px;
  background: var(--surface-sunken);
  border: 1px solid var(--hairline);
  border-radius: var(--radius-control);
  overflow-x: auto; scroll-snap-type: x mandatory; scrollbar-width: none;
  max-width: 100%;
}
.seg::-webkit-scrollbar { display: none }
.seg__item {
  flex: 0 0 auto; scroll-snap-align: center;
  padding: 6px 12px; min-height: 32px;
  border: 0; border-radius: 4px; background: transparent;
  font: inherit; font-size: 13px; color: var(--ink-muted); cursor: pointer;
  white-space: nowrap;
  transition: background var(--dur-micro) var(--ease-standard), color var(--dur-micro) var(--ease-standard);
}
.seg__item:hover { color: var(--ink) }
.seg__item[aria-checked='true'] {
  background: var(--surface-raised); color: var(--ink); font-weight: 600;
  box-shadow: var(--elev-1);
}
</style>
