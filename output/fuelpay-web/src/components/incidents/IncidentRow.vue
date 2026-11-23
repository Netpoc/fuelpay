<script setup lang="ts">
/** One incident. Shared by the generator page and the feed so they cannot drift. */
import { computed } from 'vue'
import { RouterLink } from 'vue-router'

import Figure from '@/components/ui/Figure.vue'
import { EVENT_SPEC, type Incident } from '@/lib/incidents'
import { STATUS } from '@/theme/tokens'
import { useTheme } from '@/composables/useTheme'
import { relativeTime, signedLitres } from '@/lib/format'

const props = withDefaults(
  defineProps<{
    incident: Incident
    generatorName?: string
    siteName?: string
    linkTo?: boolean
  }>(),
  { linkTo: true },
)

const { resolved } = useTheme()
const spec = computed(() => EVENT_SPEC[props.incident.event_type])
const colour = computed(() => STATUS[resolved.value][spec.value.status])
</script>

<template>
  <div class="row">
    <span class="dot" :style="{ background: colour }" aria-hidden="true">{{ spec.glyph }}</span>

    <div class="body">
      <p class="line1">
        <span class="label">{{ spec.label }}</span>
        <Figure
          v-if="incident.volume_l"
          :value="signedLitres(incident.volume_l)"
          size="sm"
          class="vol"
          :style="{ color: colour }"
        />
        <span v-if="incident.count > 1" class="over">over {{ incident.count }} readings</span>
      </p>
      <p v-if="generatorName" class="line2">
        <!-- Only link when there is a generator to link TO. A site-level
             incident carries a null generator_id, and building the route with
             it throws "Missing required param" — which took the whole subject
             line down with it, leaving every bulk-storage row nameless. -->
        <RouterLink
          v-if="linkTo && incident.generator_id"
          :to="{ name: 'generator', params: { id: incident.generator_id } }"
          class="gen"
          >{{ generatorName }}</RouterLink
        >
        <span v-else class="gen">{{ generatorName }}</span>
        <span v-if="siteName"> · {{ siteName }}</span>
      </p>
    </div>

    <time class="when" :datetime="incident.occurred_at">{{ relativeTime(incident.occurred_at) }}</time>
    <slot name="action" />
  </div>
</template>

<style scoped>
.row { display: flex; align-items: flex-start; gap: 11px; padding: 11px 2px }
.dot {
  flex: none; width: 22px; height: 22px; border-radius: 999px;
  display: inline-flex; align-items: center; justify-content: center;
  color: var(--on-solid); font-size: 10px; font-weight: 700; line-height: 1;
}
.body { flex: 1; min-width: 0 }
.line1 { margin: 0; display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px }
.label { font-size: 14px; font-weight: 600 }
.vol { font-weight: 600 }
.over { font-size: 11px; color: var(--ink-muted) }
.line2 { margin: 2px 0 0; font-size: 12px; color: var(--ink-muted) }
.gen { font-weight: 500; color: var(--ink) }
.gen:hover { text-decoration: underline }
.when { flex: none; font-size: 11px; color: var(--ink-muted); padding-top: 3px }
</style>
