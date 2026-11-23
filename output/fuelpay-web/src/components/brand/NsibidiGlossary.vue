<script setup lang="ts">
/**
 * Names the Nsibidi glyphs woven into a screen's pattern, so the background
 * reads as writing, not decoration — and carries the source credit, which is
 * required wherever the glyphs appear (netpoc docs/brand/nsibidi.md). Compact
 * port of Netpoc's footer glossary; keep the credit line verbatim.
 */
import { computed } from 'vue'
import { GLYPHS, NSIBIDI_SETS, type NsibidiSet } from '@/content/nsibidi'

const props = withDefaults(
  defineProps<{
    set?: NsibidiSet
    /** `night` for brand panels that stay dark in both themes. */
    tone?: 'theme' | 'night'
  }>(),
  { set: 'value', tone: 'theme' },
)

const glyphs = computed(() => NSIBIDI_SETS[props.set].glyphs.map((key) => ({ key, ...GLYPHS[key] })))
const hasCompound = computed(() => glyphs.value.some((g) => g.origin === 'compound'))
</script>

<template>
  <section class="gloss" :class="`gloss--${tone}`" aria-label="Nsibidi on this screen">
    <p class="gloss__lead">The pattern here is Nsibidi, the ideographic script of the Cross River region. It reads:</p>
    <ul class="gloss__list">
      <li v-for="g in glyphs" :key="g.key" :title="`Nsibidi dictionary entry ${g.entry}`">
        <svg viewBox="0 0 48 48" aria-hidden="true" focusable="false">
          <path :d="g.d" />
          <circle v-for="(dot, j) in 'dots' in g ? g.dots : []" :key="j" :cx="dot[0]" :cy="dot[1]" :r="dot[2]" />
        </svg>
        <span>
          {{ g.meaning }}<span v-if="g.origin === 'compound'" class="gloss__neo">neo</span>
        </span>
      </li>
    </ul>
    <p class="gloss__credit">
      <template v-if="hasCompound"><span class="gloss__neo">neo</span> marks a modern compound. </template>
      Symbols and meanings after the Nsịbịrị (neo-Nsibidi) dictionary, revision 23, 2015.
    </p>
  </section>
</template>

<style scoped>
.gloss {
  --g-text: var(--ink-muted);
  --g-quiet: var(--ink-subtle);
  --g-glyph: var(--interactive);
  --g-line: var(--hairline-strong);
  font-size: 12px;
  line-height: 1.45;
  color: var(--g-quiet);
}
.gloss--night {
  --g-text: var(--np-mist);
  --g-quiet: var(--np-muted);
  --g-glyph: var(--np-saffron);
  --g-line: rgb(245 242 234 / 18%);
}
.gloss__lead { margin: 0 0 8px; }
.gloss__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
}
.gloss__list li {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--g-text);
}
.gloss__list svg {
  flex: none;
  width: 20px;
  height: 20px;
  fill: none;
  stroke: var(--g-glyph);
  stroke-width: 3.2;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.gloss__list circle { fill: var(--g-glyph); stroke: none; }
.gloss__neo {
  display: inline-block;
  margin-left: 4px;
  padding: 0 5px;
  border-radius: 999px;
  border: 1px solid var(--g-line);
  font-size: 10px;
  line-height: 1.5;
  vertical-align: 1px;
}
.gloss__credit { margin: 8px 0 0; font-size: 11px; }
</style>
