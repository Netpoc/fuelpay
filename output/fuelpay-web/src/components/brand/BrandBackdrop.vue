<script setup lang="ts">
/**
 * The Netpoc brand field, layered back to front:
 *   aurora glow → Nsibidi script field → Ankara band.
 *
 * For the public brand screens only (sign-in panel, demo wizard, 404, admin
 * sign-in). Dashboards never get this: a patterned field behind live data
 * costs legibility, and the data is the product.
 *
 * Fills its positioned parent (absolute, inset 0) and is purely decorative.
 * Everything that animates stops under prefers-reduced-motion.
 */
import AnkaraPattern from './AnkaraPattern.vue'
import NsibidiPattern from './NsibidiPattern.vue'

withDefaults(
  defineProps<{
    /** Drifting saffron/violet/emerald glow, as on netpoc. */
    aurora?: boolean
    /** Nsibidi stroke opacity. Keep 0.04–0.08 behind text (brand rule). */
    nsibidi?: number
    /** Ankara wax-print: a saturated edge band, or nothing. */
    ankara?: 'band' | 'none'
    /** Where the band sits. */
    bandSide?: 'right' | 'bottom'
    /** Colour the Nsibidi strokes take. Ivory on night by default. */
    ink?: string
  }>(),
  { aurora: true, nsibidi: 0.07, ankara: 'band', bandSide: 'right', ink: 'var(--np-ivory)' },
)
</script>

<template>
  <div class="backdrop" aria-hidden="true">
    <div v-if="aurora" class="aurora">
      <span class="aurora__blob aurora__blob--saffron" />
      <span class="aurora__blob aurora__blob--violet" />
      <span class="aurora__blob aurora__blob--emerald" />
    </div>
    <NsibidiPattern v-if="nsibidi > 0" :opacity="nsibidi" :scale="150" :color="ink" />
    <div v-if="ankara === 'band'" class="band" :class="`band--${bandSide}`">
      <AnkaraPattern :scale="84" />
    </div>
  </div>
</template>

<style scoped>
.backdrop {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.aurora {
  position: absolute;
  inset: 0;
}
.aurora__blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.42;
  will-change: transform;
}
.aurora__blob--saffron {
  width: 60%;
  aspect-ratio: 1;
  top: -18%;
  left: -14%;
  background: radial-gradient(circle, var(--np-saffron), transparent 70%);
  animation: drift1 22s var(--ease-out-expo) infinite alternate;
}
.aurora__blob--violet {
  width: 64%;
  aspect-ratio: 1;
  top: 32%;
  right: -22%;
  background: radial-gradient(circle, var(--np-violet), transparent 70%);
  animation: drift2 26s var(--ease-out-expo) infinite alternate;
}
.aurora__blob--emerald {
  width: 50%;
  aspect-ratio: 1;
  bottom: -20%;
  left: 18%;
  background: radial-gradient(circle, var(--np-emerald), transparent 70%);
  opacity: 0.28;
  animation: drift3 30s var(--ease-out-expo) infinite alternate;
}
@keyframes drift1 { to { transform: translate(10%, 8%) scale(1.1) } }
@keyframes drift2 { to { transform: translate(-8%, -10%) scale(1.05) } }
@keyframes drift3 { to { transform: translate(6%, -6%) scale(1.15) } }

/* The Ankara band: dense and saturated, kept to an edge so it never sits
   behind text — the glass/Ankara tension the brand asks for. */
.band {
  position: absolute;
  overflow: hidden;
  background: var(--np-night);
}
.band--right {
  top: 0;
  right: 0;
  bottom: 0;
  width: clamp(44px, 6vw, 84px);
  border-left: 1px solid rgb(247 183 51 / 35%);
}
.band--bottom {
  left: 0;
  right: 0;
  bottom: 0;
  height: 42px;
  border-top: 1px solid rgb(247 183 51 / 35%);
}

@media (prefers-reduced-motion: reduce) {
  .aurora__blob { animation: none }
}
</style>
