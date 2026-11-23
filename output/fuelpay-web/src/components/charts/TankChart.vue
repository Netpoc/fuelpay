<script setup lang="ts">
/**
 * A tank's measured level over time, with its movements underneath.
 *
 * The one thing this chart must never do is draw a continuous line across a
 * period with no readings. The API omits empty buckets, so a naive plot joins
 * the level before an outage to the level after it — a straight, confident
 * line through precisely the window in which fuel is most likely to have gone
 * missing. Gaps are detected and broken with nulls, and shaded, so an outage
 * reads as an absence of knowledge rather than as a smooth decline.
 *
 * Two stacked panels sharing one x-axis: litres of stock above, litres moved
 * below. Same quantity, very different magnitudes — a shared axis would flatten
 * the movement bars to nothing.
 */
import { computed, ref } from 'vue'
import { useElementSize, useMediaQuery } from '@vueuse/core'
import VChart from 'vue-echarts'

import '@/plugins/echarts'
import type { Incident } from '@/lib/incidents'
import { isFuelLoss } from '@/lib/incidents'
import type { TankSeriesPoint } from '@/api/types'
import { chartTokens } from '@/theme/chart'
import { useTheme } from '@/composables/useTheme'
import { litres } from '@/lib/format'

const props = withDefaults(
  defineProps<{
    points: TankSeriesPoint[]
    incidents: Incident[]
    capacityL: number
    reorderThresholdPct: number
    bucketMinutes?: number
    kind?: 'DAY' | 'BULK'
    height?: number
  }>(),
  { bucketMinutes: 5, kind: 'DAY', height: 380 },
)

const thresholdL = computed(() => (props.capacityL * props.reorderThresholdPct) / 100)

const { resolved } = useTheme()
const C = computed(() => chartTokens(resolved.value))

const root = ref<HTMLElement>()
const { width } = useElementSize(root)
const narrow = computed(() => width.value > 0 && width.value < 480)
const coarse = useMediaQuery('(pointer: coarse)')

const AXIS_LINE = computed(() => ({ lineStyle: { color: C.value.axis } }))
const SPLIT_LINE = computed(() => ({ lineStyle: { color: C.value.split } }))

/**
 * A bucket is "missing" when the step to the next one exceeds the bucket size.
 *
 * 1.5x rather than 1x: bucket edges are epoch-aligned, so consecutive buckets
 * can sit a hair over one interval apart from rounding alone, and a bare `>`
 * would punch a hole in an unbroken series.
 */
const GAP_FACTOR = 1.5

interface Gap {
  from: number
  to: number
}

/**
 * A series with an explicit null inserted at every reporting gap.
 *
 * ECharts joins across a missing x value but breaks on an explicit null, so
 * the gap has to be stated rather than merely left out. Every line drawn on
 * this chart must go through here — a second series plotted from the raw
 * points would quietly bridge the outage the first one correctly breaks, which
 * is worse than not breaking either, because it looks deliberate.
 */
function gapped(pick: (point: TankSeriesPoint) => number): [number, number | null][] {
  const out: [number, number | null][] = []
  const step = props.bucketMinutes * 60_000
  props.points.forEach((point, index) => {
    const at = new Date(point.time).getTime()
    const previous = props.points[index - 1]
    if (previous) {
      const previousAt = new Date(previous.time).getTime()
      if (at - previousAt > step * GAP_FACTOR) out.push([previousAt + step, null])
    }
    out.push([at, pick(point)])
  })
  return out
}

const levelData = computed(() => gapped((point) => point.level_l))

/** The same gaps, as bands, so the break is legible and not just an absence. */
const gaps = computed<Gap[]>(() => {
  const out: Gap[] = []
  const step = props.bucketMinutes * 60_000
  props.points.forEach((point, index) => {
    const previous = props.points[index - 1]
    if (!previous) return
    const at = new Date(point.time).getTime()
    const previousAt = new Date(previous.time).getTime()
    if (at - previousAt > step * GAP_FACTOR) out.push({ from: previousAt, to: at })
  })
  return out
})

const minData = computed(() => gapped((point) => point.level_min_l))

/**
 * Movement bars. Consumption and transfer are shown as separate series rather
 * than summed: for a bulk tank the only outflow IS the transfer, and merging
 * the two would make a day tank's burn indistinguishable from a bulk tank's
 * pumping.
 */
const movedData = computed(() =>
  props.points.map((point) => [
    new Date(point.time).getTime(),
    props.kind === 'BULK' ? point.transferred_l : point.consumed_l,
  ]),
)

const incidentBands = computed(() =>
  props.incidents.map((incident) => {
    const from = new Date(incident.occurred_at).getTime()
    const to = new Date(incident.ended_at).getTime()
    const minWidth = props.bucketMinutes * 60_000
    const loss = isFuelLoss(incident.event_type)
    return [
      { xAxis: from, itemStyle: { color: loss ? C.value.bandDrain : C.value.bandRefill } },
      { xAxis: Math.max(to, from + minWidth) },
    ]
  }),
)

/** Outage bands, drawn on the same markArea mechanism as incidents. */
const gapBands = computed(() =>
  gaps.value.map((gap) => [
    { xAxis: gap.from, itemStyle: { color: C.value.split, opacity: 0.55 } },
    { xAxis: gap.to },
  ]),
)

const option = computed(() => ({
  animation: false,
  grid: [
    { left: narrow.value ? 48 : 62, right: 16, top: 20, height: '52%' },
    { left: narrow.value ? 48 : 62, right: 16, top: '70%', height: '18%' },
  ],
  tooltip: {
    trigger: 'axis',
    backgroundColor: C.value.tooltipBg,
    borderColor: C.value.tooltipBorder,
    textStyle: { color: C.value.textStrong },
    axisPointer: { type: 'line', lineStyle: { color: C.value.axis } },
  },
  axisPointer: { link: [{ xAxisIndex: 'all' }] },
  xAxis: [
    { type: 'time', gridIndex: 0, axisLine: AXIS_LINE.value, axisLabel: { color: C.value.text } },
    {
      type: 'time',
      gridIndex: 1,
      axisLine: AXIS_LINE.value,
      axisLabel: { color: C.value.text },
    },
  ],
  yAxis: [
    {
      type: 'value',
      gridIndex: 0,
      name: 'Litres',
      nameTextStyle: { color: C.value.text, align: 'left' },
      max: props.capacityL,
      axisLabel: { color: C.value.text },
      splitLine: SPLIT_LINE.value,
    },
    {
      type: 'value',
      gridIndex: 1,
      name: props.kind === 'BULK' ? 'Transferred' : 'Burned',
      nameTextStyle: { color: C.value.text, align: 'left' },
      axisLabel: { color: C.value.text },
      splitLine: SPLIT_LINE.value,
    },
  ],
  dataZoom: coarse.value
    ? [{ type: 'slider', xAxisIndex: [0, 1], height: 18, bottom: 2 }]
    : [
        { type: 'inside', xAxisIndex: [0, 1] },
        { type: 'slider', xAxisIndex: [0, 1], height: 18, bottom: 2 },
      ],
  series: [
    {
      name: 'Level',
      type: 'line',
      showSymbol: false,
      // The whole point. Left true, ECharts would bridge every outage.
      connectNulls: false,
      data: levelData.value,
      lineStyle: { width: 2, color: C.value.fuel },
      areaStyle: { color: C.value.fuelArea },
      markLine: {
        silent: true,
        symbol: 'none',
        data: [
          {
            yAxis: thresholdL.value,
            lineStyle: { color: C.value.watch, type: 'dashed' },
            label: {
              formatter: `Reorder ${props.reorderThresholdPct}%`,
              color: C.value.watch,
              position: 'insideStartTop',
            },
          },
        ],
      },
      markArea: { silent: true, data: [...incidentBands.value, ...gapBands.value] },
    },
    {
      name: 'Bucket low',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      data: minData.value,
      lineStyle: { width: 1, type: 'dotted', color: C.value.fuel, opacity: 0.7 },
    },
    {
      name: props.kind === 'BULK' ? 'Transferred out' : 'Burned',
      type: 'bar',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: movedData.value,
      itemStyle: { color: C.value.load },
    },
  ],
}))

/**
 * A text alternative, because an ECharts canvas is invisible to assistive tech.
 * The gap count is stated explicitly — it is the one fact a sighted reader gets
 * from the shading that a table of values would not convey.
 */
const summary = computed(() => {
  if (!props.points.length) return 'Tank level chart, no readings in this window'
  const first = props.points[0]!
  const last = props.points[props.points.length - 1]!
  const losses = props.incidents.filter((i) => isFuelLoss(i.event_type)).length
  return [
    `Tank level over ${props.points.length} points`,
    `from ${litres(first.level_l)} to ${litres(last.level_l)}`,
    `capacity ${litres(props.capacityL)}`,
    gaps.value.length ? `${gaps.value.length} reporting gap${gaps.value.length > 1 ? 's' : ''}` : '',
    losses ? `${losses} unexplained loss${losses > 1 ? 'es' : ''}` : '',
  ]
    .filter(Boolean)
    .join(', ')
})
</script>

<template>
  <div ref="root" class="wrap">
    <p class="sr-only">{{ summary }}</p>
    <VChart
      v-if="points.length"
      :option="option"
      :style="{ height: `${height}px` }"
      autoresize
      aria-hidden="true"
    />
    <p v-else class="empty">No readings in this window.</p>
    <p v-if="gaps.length" class="gapnote">
      {{ gaps.length }} reporting gap{{ gaps.length > 1 ? 's' : '' }} shaded — the sensor was not
      reporting, so the level through {{ gaps.length > 1 ? 'those windows' : 'that window' }} is
      unknown.
    </p>
  </div>
</template>

<style scoped>
.wrap { width: 100% }
.empty { padding: 40px 0; text-align: center; color: var(--ink-muted); font-size: 13px }
.gapnote { margin: 6px 0 0; font-size: 11px; color: var(--ink-muted); line-height: 1.45 }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
</style>
