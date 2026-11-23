<script setup lang="ts">
/**
 * An open-top standing diesel tank, filled to the level a sensor reported.
 *
 * The fuel is diesel-amber and stays that way at every level, because that is
 * what is in the tank. State is carried instead by the level badge, the
 * reorder marker on the scale, and the alert dot — colouring the fuel itself
 * red would be inventing a property the liquid does not have, and would clash
 * with the calibration scale that is doing the real quantitative work.
 *
 * What carries meaning, none of it decoration:
 *   - the surface height against the calibration scale is the fill,
 *   - the dashed marker is this generator's own reorder threshold,
 *   - the surface trembles only while the engine runs,
 *   - the alert dot appears only for a live incident.
 */
import { computed, onUnmounted, ref, useId, watch } from 'vue'
import { TransitionPresets, useElementSize, usePreferredReducedMotion, useTransition } from '@vueuse/core'

import {
  BADGE_W,
  BADGE_X,
  BOTTOM_Y,
  CX,
  LEADER_END,
  LABEL_X,
  LEFT,
  MAJOR_PCT,
  MAJOR_TICK_X,
  MINOR_PCT,
  MINOR_TICK_X,
  RIGHT,
  RX,
  RY,
  SCALE_X,
  TOP_Y,
  VIEWBOX,
  fillFraction,
  surfaceY,
  thresholdY,
} from './geometry'
import { AGITATION_EPSILON, RUNNING_AGITATION, STILL_AGITATION } from './wave'
import { STATE_LABEL, tankState } from './state'
import { STATUS } from '@/theme/tokens'
import { useTheme } from '@/composables/useTheme'
import { litres, percent } from '@/lib/format'

const props = withDefaults(
  defineProps<{
    levelL: number
    capacityL: number
    reorderThresholdPct: number
    engineRunning?: boolean
    size?: 'sm' | 'md' | 'lg'
    /** Draws the attention dot. Set from the incidents store. */
    alert?: 'drain' | 'low' | null
    /** A level jump beyond this share of capacity reads as a refill or a drain. */
    jumpThreshold?: number
    /**
     * Which tier this vessel is.
     *
     * A day tank is the open-top drum inside the genset housing. Bulk storage
     * is a sealed vessel with a manway — drawing both the same way would make
     * the two tiers indistinguishable at a glance, which is the one thing this
     * graphic most needs to convey now that there are two of them.
     */
    kind?: 'DAY' | 'BULK'
    /**
     * The sensor is not reporting, so there is NO level to draw.
     *
     * Renders an empty, muted vessel — not a tank at zero, and never the last
     * known level. An unobserved tank has no level, and drawing a plausible
     * one is the precise failure this product exists to prevent.
     */
    unknown?: boolean
  }>(),
  {
    engineRunning: false,
    size: 'md',
    alert: null,
    jumpThreshold: 0.05,
    kind: 'DAY',
    unknown: false,
  },
)

// Every <defs> id must be unique per instance. Twelve tanks in a grid each
// declaring id="fuel" would all paint from whichever gradient the document
// resolved first — the classic SVG-component bug, and it presents as a
// rendering glitch rather than as an id collision.
const uid = useId()
const fuelId = `fuel-${uid}`
const glassId = `glass-${uid}`
const clipId = `tankclip-${uid}`

/**
 * Max widths, not fixed widths. The wrapper is fluid and the SVG takes its
 * aspect ratio from the viewBox, so proportions are exact at any size.
 *
 * The old `lg` was a hard 380px, which inside the detail panel's padding
 * needed more room than a 390px phone has — the app's only horizontal
 * overflow, and the screenshot harness catches it if it ever returns.
 */
const MAX_WIDTH = {
  sm: 'clamp(72px, 22vw, 92px)',
  md: 'clamp(170px, 44vw, 240px)',
  lg: 'clamp(180px, 62vw, 330px)',
} as const

/**
 * The scale and placard appear only once there is room to READ them, which is
 * a question about rendered width, not about which size was requested — a
 * large tank squeezed into a narrow column has to drop them too. At a fleet
 * card's width "100%" would render about four pixels tall: present but
 * illegible, which is worse than absent.
 */
const root = ref<HTMLElement>()
const { width } = useElementSize(root)
const detailed = computed(() => width.value >= 190)
const viewBox = computed(() => (detailed.value ? VIEWBOX.full : VIEWBOX.compact))
/** Straight from the viewBox, so the drawing never letterboxes. */
const ratio = computed(() => (detailed.value ? '466 / 372' : '296 / 372'))

// An unreported tank draws empty. `fraction` is the only place this needs
// forcing: everything downstream — surface, badge, aria — reads from it.
const fraction = computed(() =>
  props.unknown ? 0 : fillFraction(props.levelL, props.capacityL),
)
const fuelPct = computed(() => fraction.value * 100)
const state = computed(() => tankState(fuelPct.value, props.reorderThresholdPct))
const { resolved } = useTheme()
const stateColour = computed(() => STATUS[resolved.value][state.value])

const surface = computed(() => surfaceY(fraction.value))
const threshold = computed(() => thresholdY(props.reorderThresholdPct))

const reducedMotion = usePreferredReducedMotion()
const still = computed(() => reducedMotion.value === 'reduce')

// Ease the trembling away rather than cutting it: an engine stopping should
// look like fuel settling, which takes a moment.
const targetAgitation = computed(() =>
  props.engineRunning && !still.value ? RUNNING_AGITATION : STILL_AGITATION,
)
const agitation = useTransition(targetAgitation, {
  duration: 800,
  transition: TransitionPresets.easeOutCubic,
})
/** Nothing composited while the surface is flat. */
const trembling = computed(() => agitation.value > AGITATION_EPSILON)

const majorTicks = computed(() => MAJOR_PCT.map((pct) => ({ pct, y: thresholdY(pct) })))
const minorTicks = computed(() => MINOR_PCT.map((pct) => thresholdY(pct)))

// --- the refill / drain moment ---
type Phase = 'idle' | 'refill' | 'drain'
const phase = ref<Phase>('idle')
let phaseTimer: ReturnType<typeof setTimeout> | undefined

watch(
  () => props.levelL,
  (next, previous) => {
    if (previous === undefined || !props.capacityL) return
    const delta = (next - previous) / props.capacityL
    if (Math.abs(delta) < props.jumpThreshold) return

    phase.value = delta > 0 ? 'refill' : 'drain'
    // One timer, always cleared: back-to-back refills must not stack timeouts
    // and leave the highlight stuck on.
    clearTimeout(phaseTimer)
    phaseTimer = setTimeout(() => (phase.value = 'idle'), 2600)
  },
)

onUnmounted(() => clearTimeout(phaseTimer))

const vessel = computed(() => (props.kind === 'BULK' ? 'Bulk storage tank' : 'Diesel day tank'))

const ariaLabel = computed(() => {
  if (props.unknown) {
    return `${vessel.value}, ${litres(props.capacityL)} capacity, sensor not reporting, level unknown`
  }
  return [
    `${vessel.value} ${Math.round(fuelPct.value)} percent`,
    `${litres(props.levelL)} of ${litres(props.capacityL)}`,
    STATE_LABEL[state.value],
    // Bulk storage has no engine attached, so the engine's state says nothing
    // about it and would only mislead a screen-reader user.
    props.kind === 'BULK' ? '' : props.engineRunning ? 'engine running' : 'engine stopped',
    props.alert === 'drain' ? 'suspected drain' : props.alert === 'low' ? 'low fuel alert' : '',
  ]
    .filter(Boolean)
    .join(', ')
})
</script>

<template>
  <div
    class="tank"
    :class="[
      `tank--${state}`,
      `tank--${phase}`,
      `tank--${kind.toLowerCase()}`,
      { 'tank--trembling': trembling, 'tank--unknown': unknown },
    ]"
    ref="root"
    :style="{ maxWidth: MAX_WIDTH[size], aspectRatio: ratio, '--state-colour': stateColour }"
  >
    <svg
      width="100%"
      height="100%"
      :viewBox="viewBox"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      :aria-label="ariaLabel"
    >
      <defs>
        <!-- Horizontal ramp, not vertical: it is the curve of the cylinder
             catching light, so it must run across the barrel. -->
        <!-- Stops are CLASSED, not given stop-color attributes: a
             presentation attribute does not reliably accept var(), so this is
             the only way the gradient can follow the theme. -->
        <linearGradient :id="fuelId" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" class="fuel-1" />
          <stop offset="0.3" class="fuel-2" />
          <stop offset="0.65" class="fuel-3" />
          <stop offset="1" class="fuel-4" />
        </linearGradient>

        <linearGradient :id="glassId" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" class="glass-1" />
          <stop offset="0.28" class="glass-2" />
          <stop offset="0.7" class="glass-3" />
          <stop offset="1" class="glass-4" />
        </linearGradient>

        <!-- Union of walls and both end caps: the cylinder's silhouette.
             Clipping to it lets the fuel be one fixed shape that simply slides,
             so a level change animates on the compositor instead of forcing a
             new path string every frame. -->
        <clipPath :id="clipId">
          <rect :x="LEFT" :y="TOP_Y" :width="RX * 2" :height="BOTTOM_Y - TOP_Y" />
          <ellipse :cx="CX" :cy="TOP_Y" :rx="RX" :ry="RY" />
          <ellipse :cx="CX" :cy="BOTTOM_Y" :rx="RX" :ry="RY" />
        </clipPath>
      </defs>

      <!-- ---------- fuel ---------- -->
      <g :clip-path="`url(#${clipId})`">
        <g class="fuel" :style="{ transform: `translateY(${surface}px)` }">
          <!-- Deep enough to reach the floor from any level; the clip trims it. -->
          <rect :x="LEFT" y="0" :width="RX * 2" :height="BOTTOM_Y - TOP_Y + RY * 2" :fill="`url(#${fuelId})`" />
          <g class="surface">
            <ellipse cx="0" cy="0" :rx="RX" :ry="RY" class="surface-fill" :transform="`translate(${CX} 0)`" />
            <ellipse
              cx="0"
              cy="0"
              :rx="RX"
              :ry="RY"
              fill="none"
              class="surface-edge"
              stroke-width="1"
              :transform="`translate(${CX} 0)`"
            />
          </g>
          <!-- Light bouncing off the inside of the far wall. -->
          <path
            class="fuel-sheen sheen-stroke"
            :d="`M${LEFT + 20} 90 q0 60 14 84`"
            fill="none"
            stroke-width="8"
            stroke-linecap="round"
          />
        </g>
      </g>

      <!-- ---------- glass shell ---------- -->
      <path
        :d="`M${LEFT} ${TOP_Y} L${LEFT} ${BOTTOM_Y} A${RX} ${RY} 0 0 0 ${RIGHT} ${BOTTOM_Y} L${RIGHT} ${TOP_Y}`"
        :fill="`url(#${glassId})`"
      />
      <path
        :d="`M${LEFT} ${TOP_Y} L${LEFT} ${BOTTOM_Y} A${RX} ${RY} 0 0 0 ${RIGHT} ${BOTTOM_Y} L${RIGHT} ${TOP_Y}`"
        fill="none"
        class="shell-stroke"
        stroke-width="1.5"
      />
      <!-- Top: an open rim on a day tank, a sealed head with a manway on bulk
           storage. The silhouette is what separates the two tiers at a glance,
           so it is doing real work, not decoration. -->
      <template v-if="kind === 'BULK'">
        <ellipse
          :cx="CX"
          :cy="TOP_Y"
          :rx="RX"
          :ry="RY"
          :fill="`url(#${glassId})`"
          class="shell-stroke bulk-head"
          stroke-width="1.5"
        />
        <!-- manway / inspection hatch -->
        <ellipse
          :cx="CX"
          :cy="TOP_Y - 3"
          :rx="30"
          :ry="9"
          class="shell-stroke hatch"
          stroke-width="1.5"
        />
        <!-- fill point, offset so the head does not read as symmetrical -->
        <ellipse
          :cx="CX + 70"
          :cy="TOP_Y + 6"
          :rx="12"
          :ry="4"
          class="shell-stroke hatch"
          stroke-width="1.2"
        />
      </template>
      <template v-else>
        <!-- open rim -->
        <ellipse :cx="CX" :cy="TOP_Y" :rx="RX" :ry="RY" fill="none" class="shell-stroke" stroke-width="1.5" />
        <ellipse
          :cx="CX"
          :cy="TOP_Y"
          :rx="RX - 8"
          :ry="RY - 4"
          fill="none"
          class="rim-inner"
          stroke-width="1"
          opacity="0.6"
        />
      </template>
      <!-- specular stripe on the near wall -->
      <path
        :d="`M${LEFT + 16} ${TOP_Y + 22} L${LEFT + 16} ${BOTTOM_Y - 4}`"
        class="specular"
        stroke-width="7"
        stroke-linecap="round"
      />

      <!-- ---------- placard ---------- -->
      <g v-if="detailed">
        <rect :x="CX - 54" y="130" width="108" height="38" rx="6" fill="var(--np-saffron)" class="placard" stroke-width="1.5" />
        <text :x="CX" y="148" text-anchor="middle" class="placard-title">DIESEL</text>
        <text :x="CX" y="162" text-anchor="middle" class="placard-sub">
          {{ kind === 'BULK' ? 'AGO — bulk store' : 'AGO — flammable' }}
        </text>
      </g>

      <!-- ---------- calibration scale ---------- -->
      <template v-if="detailed">
        <g class="major">
          <line :x1="SCALE_X" :y1="TOP_Y" :x2="SCALE_X" :y2="BOTTOM_Y" />
          <line
            v-for="tick in majorTicks"
            :key="`M${tick.pct}`"
            :x1="SCALE_X"
            :y1="tick.y"
            :x2="MAJOR_TICK_X"
            :y2="tick.y"
          />
        </g>
        <g class="minor">
          <line
            v-for="y in minorTicks"
            :key="`m${y}`"
            :x1="SCALE_X"
            :y1="y"
            :x2="MINOR_TICK_X"
            :y2="y"
          />
        </g>
        <g class="scale-label">
          <text v-for="tick in majorTicks" :key="`L${tick.pct}`" :x="LABEL_X" :y="tick.y + 4">
            {{ tick.pct }}%
          </text>
        </g>
      </template>

      <!-- ---------- reorder threshold ---------- -->
      <g class="threshold">
        <line :x1="LEFT - 6" :y1="threshold" :x2="detailed ? SCALE_X : RIGHT + 6" :y2="threshold" />
        <polygon
          :points="`${LEFT - 6},${threshold} ${LEFT - 15},${threshold - 5} ${LEFT - 15},${threshold + 5}`"
        />
      </g>

      <!-- ---------- level indicator ---------- -->
      <!-- Suppressed entirely when the sensor is dark. A leader line pointing
           at the floor with a "0%" badge would assert an empty tank, which is
           a measurement nobody took. -->
      <g v-if="!unknown" class="level" :style="{ transform: `translateY(${surface}px)` }">
        <line :x1="RIGHT + 2" y1="0" :x2="detailed ? LEADER_END : RIGHT + 30" y2="0" />
        <template v-if="detailed">
          <rect :x="BADGE_X" y="-13" :width="BADGE_W" height="26" rx="6" :fill="stateColour" />
          <text :x="BADGE_X + BADGE_W / 2" y="5" text-anchor="middle" class="level-value">
            {{ Math.round(fuelPct) }}%
          </text>
        </template>
      </g>

      <!-- ---------- no signal ---------- -->
      <g v-else class="nosignal">
        <text :x="CX" :y="(TOP_Y + BOTTOM_Y) / 2 + 40" text-anchor="middle" class="nosignal__glyph">
          ?
        </text>
        <text :x="CX" :y="(TOP_Y + BOTTOM_Y) / 2 + 74" text-anchor="middle" class="nosignal__text">
          NO SIGNAL
        </text>
      </g>

      <!-- ---------- live incident ---------- -->
      <g v-if="alert" class="alert" :class="`alert--${alert}`">
        <circle class="alert__halo" :cx="LEFT + 40" :cy="TOP_Y + 56" r="24" />
        <circle class="alert__dot" :cx="LEFT + 40" :cy="TOP_Y + 56" r="18" />
        <text :x="LEFT + 40" :y="TOP_Y + 63" text-anchor="middle" class="alert__glyph">
          {{ alert === 'drain' ? '▼' : '!' }}
        </text>
      </g>
    </svg>

    <div class="readout">
      <template v-if="unknown">
        <span class="readout__pct readout__pct--unknown tabular">—</span>
        <span v-if="detailed" class="readout__litres">no signal</span>
      </template>
      <template v-else>
        <span class="readout__pct tabular">{{ percent(fuelPct, 0) }}</span>
        <span v-if="detailed" class="readout__litres tabular">{{ litres(levelL) }}</span>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* --- theme-following paint ------------------------------------------------
   Diesel stays amber in both themes — the liquid's colour is a fact about the
   liquid. But the dark ramp is darkened, because the light-mode ramp glows
   like neon against a dark surface. The glass inverts to a cool steel and the
   specular stripe drops hard; missing that is the single biggest dark-mode
   tell on this component. */
.fuel-1 { stop-color: var(--tank-fuel-1) }
.fuel-2 { stop-color: var(--tank-fuel-2) }
.fuel-3 { stop-color: var(--tank-fuel-3) }
.fuel-4 { stop-color: var(--tank-fuel-4) }
.surface-fill { fill: var(--tank-surface) }
.surface-edge { stroke: var(--tank-surface-edge) }
.sheen-stroke { stroke: var(--tank-surface) }

.glass-1 { stop-color: var(--tank-glass-1); stop-opacity: var(--tank-glass-o1) }
.glass-2 { stop-color: var(--tank-glass-2); stop-opacity: var(--tank-glass-o2) }
.glass-3 { stop-color: var(--tank-glass-3); stop-opacity: var(--tank-glass-o3) }
.glass-4 { stop-color: var(--tank-glass-4); stop-opacity: var(--tank-glass-o4) }

.shell-stroke { stroke: var(--tank-shell) }
.rim-inner { stroke: var(--tank-rim); opacity: .6 }
.specular { stroke: #ffffff; opacity: var(--tank-specular) }
/* The DIESEL placard keeps its hazard yellow in both themes. It depicts a
   physical safety label; theming it would be a lie. */
.placard { stroke: var(--tank-placard-stroke) }

.tank {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

/* The level change itself. */
.fuel,
.level {
  transition: transform 900ms cubic-bezier(0.4, 0, 0.2, 1);
}

.fuel-sheen {
  opacity: 0.5;
}

/* Surface trembling. Paused outright when flat, so a stopped fleet composites
   nothing at all. */
.surface {
  transform-origin: center;
  animation: tremble 2.6s ease-in-out infinite;
  animation-play-state: paused;
}
.tank--trembling .surface {
  animation-play-state: running;
}
@keyframes tremble {
  0%,
  100% {
    transform: scale(1, 1);
  }
  50% {
    transform: scale(1.008, 1.09);
  }
}

.placard-title {
  font-size: 15px;
  font-weight: 700;
  /* Fixed in both themes: this is a printed safety label on the tank, not a
     themed surface. */
  fill: var(--np-night-2);
}
.placard-sub {
  font-size: 10px;
  fill: var(--np-night-3);
}

.major line {
  stroke: var(--ink);
  stroke-width: 1.5;
}
.minor line {
  stroke: var(--ink-subtle);
  stroke-width: 1;
}
.scale-label text {
  font-size: 12px;
  fill: var(--ink);
  font-variant-numeric: tabular-nums;
}

.threshold line {
  stroke: var(--ink-muted);
  stroke-width: 1.6;
  stroke-dasharray: 6 4;
  opacity: 0.75;
}
.threshold polygon {
  fill: var(--ink-muted);
  opacity: 0.75;
}

.level line {
  stroke: var(--state-colour);
  stroke-width: 2;
  stroke-dasharray: 5 3;
}
.level-value {
  font-size: 14px;
  font-weight: 700;
  fill: var(--on-solid);
  font-variant-numeric: tabular-nums;
}

/* --- live incident --- */
.alert__dot {
  fill: var(--status-critical);
}
.alert__halo {
  fill: var(--status-critical);
  opacity: 0.25;
  animation: pulse 1.9s ease-out infinite;
  transform-box: fill-box;
  transform-origin: center;
}
.alert--low .alert__dot,
.alert--low .alert__halo {
  fill: var(--status-watch);
}
.alert__glyph {
  fill: var(--on-solid);
  font-size: 18px;
  font-weight: 700;
}
@keyframes pulse {
  0% {
    transform: scale(0.8);
    opacity: 0.45;
  }
  70% {
    transform: scale(1.55);
    opacity: 0;
  }
  100% {
    opacity: 0;
  }
}

/* A refill settles; a drain accelerates. The easing is the tell — an ease-in
   fall reads as something going wrong, which is exactly what it is. */
.tank--refill .fuel,
.tank--refill .level {
  transition-duration: 1800ms;
  transition-timing-function: cubic-bezier(0.16, 1, 0.3, 1);
}
.tank--drain .fuel,
.tank--drain .level {
  transition-duration: 1800ms;
  transition-timing-function: cubic-bezier(0.7, 0, 0.84, 0);
}

.readout {
  display: flex;
  align-items: baseline;
  gap: 6px;
  line-height: 1.1;
}
.readout__pct {
  font-weight: 600;
  font-size: 15px;
  color: var(--state-colour);
}
.readout__litres {
  font-size: 12px;
  color: var(--ink-muted);
}

/* --- bulk storage --- */
/* The sealed head reads as metal, not as the open glass drum. Slightly darker
   than the shell so the cylinder still turns away from the light. */
.bulk-head { opacity: .92 }
.hatch { fill: none; opacity: .55 }

/* --- no signal ---
   The vessel is drawn but drained of colour and contrast. It must not read as
   an empty tank — hence the glyph and the word, not just a pale drawing. */
.tank--unknown svg { opacity: .55; filter: saturate(0.25) }
.nosignal__glyph {
  font-size: 46px;
  font-weight: 700;
  fill: var(--ink-muted);
}
.nosignal__text {
  font-size: 15px;
  font-weight: 700;
  letter-spacing: .1em;
  fill: var(--ink-muted);
}
.readout__pct--unknown { color: var(--ink-muted) }

/* Reduced motion: the level still updates, just instantly, and the alert still
   shows — it simply stops pulsing. No information is lost. */
@media (prefers-reduced-motion: reduce) {
  .surface,
  .alert__halo {
    animation: none !important;
  }
  .fuel,
  .level {
    transition: none !important;
  }
}
</style>
