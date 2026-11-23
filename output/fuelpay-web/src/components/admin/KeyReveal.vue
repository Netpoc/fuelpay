<script setup lang="ts">
/** A newly issued API key, shown once, with a copy button. */
import { ref } from 'vue'
import { Alert, Button, Input } from 'ant-design-vue'

defineProps<{ apiKey: string; label?: string }>()
const copied = ref(false)

async function copy(value: string) {
  try {
    await navigator.clipboard.writeText(value)
    copied.value = true
  } catch {
    /* clipboard refused; the field is still selectable */
  }
}
</script>

<template>
  <div class="reveal">
    <Alert
      type="warning"
      show-icon
      message="Copy this key now"
      description="It is shown once. Only a hash is stored, so it cannot be retrieved later — issue a new one if it is lost."
    />
    <div class="row">
      <Input :value="apiKey" readonly class="mono" :aria-label="label ?? 'API key'" />
      <Button type="primary" @click="copy(apiKey)">{{ copied ? 'Copied' : 'Copy' }}</Button>
    </div>
  </div>
</template>

<style scoped>
.reveal { display: flex; flex-direction: column; gap: 10px }
.row { display: flex; gap: 8px }
.mono :deep(input), .mono { font-family: 'IBM Plex Mono', monospace; font-size: 12px }
</style>
