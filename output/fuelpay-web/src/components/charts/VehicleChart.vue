<script setup lang="ts">
/**
 * A tractor's fuel level over time, with engine work underneath.
 *
 * Top panel: tank litres (the bucket MINIMUM — a siphon is a step down, and a
 * mean would round its corner off). Incidents are marked on it where they
 * happened. Bottom panel: fuel rate as the engine reports it, against RPM, so
 * a level falling faster than the burn explains is visible by eye.
 *
 * Gaps are broken with nulls exactly as in TankChart: a machine parked with
 * its telematics asleep must not be drawn as a smooth line across the night.
 */
import { computed, ref } from 'vue'
import { useElementSize, useMediaQuery } from '@vueuse/core'
import VChart from 'vue-echarts'

import '@/plugins/echarts'
import type { Event, VehicleSeriesPoint } from '@/api/types'
import { EVENT_SPEC, isFuelLoss } from '@/lib/incidents'
import { chartTokens, CHART_FONT } from '@/theme/chart'
import { useTheme } from '@/composables/useTheme'
import { litres } from '@/lib/format'

const props = withDefaults(
  defineProps<{
    points: VehicleSeriesPoint[]
    events: Event[]
    capacityL: number
    bucketMinutes: number
    height?: number
  }>(),
  { height: 380 },
)

const { resolved } = useTheme()
const C = computed(() => chartTokens(resolved.value))
const root = ref<HTMLElement>()
const { width } = useElementSize(root)
const narrow = computed(() => width.value > 0 && width.value < 480)
const coarse = useMediaQuery('(pointer: coarse)')

// Off-engine samples arrive every 5 minutes, so anything wider than both the
// bucket and that cadence is a real silence.
const GAP_MS = computed(() => Math.max(props.bucketMinutes, 5) * 60_000 * 2.5)

function gapped(pick: (p: VehicleSeriesPoint) => number | null) {
  const out: [number, number | null][] = []
  props.points.forEach((point, i) => {
    const t = new Date(point.time).getTime()
    const prev = props.points[i - 1]
    if (prev && t - new Date(prev.time).getTime() > GAP_MS.value) out.push([t - 1, null])
    out.push([t, pick(point)])
  })
  return out
}

const MARKED = ['REFILL', 'SUSPECTED_DRAIN', 'SHORT_FILL', 'OVERCONSUMPTION', 'MISUSE'] as const
const markers = computed(() =>
  props.events
    .filter((e) => (MARKED as readonly string[]).includes(e.event_type))
    .map((e) => {
      const spec = EVENT_SPEC[e.event_type]
      const color = C.value[spec.status === 'critical' ? 'critical' : spec.status === 'watch' ? 'watch' : 'ok']
      return {
        coord: [new Date(e.occurred_at).getTime(), e.fuel_level_l ?? 0],
        value: spec.glyph || '•',
        name: spec.label,
        symbol: 'pin',
        symbolSize: 26,
        symbolRotate: isFuelLoss(e.event_type) ? 180 : 0,
        itemStyle: { color, borderColor: C.value.markHalo, borderWidth: 1.5 },
        label: { show: false },
      }
    }),
)

const option = computed(() => ({
  animation: false,
  textStyle: { fontFamily: CHART_FONT },
  grid: [
    { left: narrow.value ? 44 : 56, right: narrow.value ? 44 : 56, top: 24, height: '50%' },
    { left: narrow.value ? 44 : 56, right: narrow.value ? 44 : 56, top: '68%', height: '20%' },
  ],
  tooltip: {
    trigger: 'axis',
    backgroundColor: C.value.tooltipBg,
    borderColor: C.value.tooltipBorder,
    textStyle: { color: C.value.textStrong },
    axisPointer: { type: 'line', lineStyle: { color: C.value.axis } },
  },
  axisPointer: { link: [{ xAxisIndex: 'all' }] },
  xAxis: [0, 1].map((gridIndex) => ({
    type: 'time',
    gridIndex,
    axisLine: { lineStyle: { color: C.value.axis } },
    axisLabel: { color: C.value.text, show: gridIndex === 1 },
  })),
  yAxis: [
    {
      type: 'value',
      gridIndex: 0,
      name: 'Litres',
      max: props.capacityL,
      min: 0,
      nameTextStyle: { color: C.value.text, align: 'left' },
      axisLabel: { color: C.value.text },
      splitLine: { lineStyle: { color: C.value.split } },
    },
    {
      type: 'value',
      gridIndex: 1,
      name: 'L/h',
      nameTextStyle: { color: C.value.text, align: 'left' },
      axisLabel: { color: C.value.text },
      splitLine: { lineStyle: { color: C.value.split } },
    },
    {
      type: 'value',
      gridIndex: 1,
      name: 'rpm',
      position: 'right',
      nameTextStyle: { color: C.value.text, align: 'right' },
      axisLabel: { color: C.value.text },
      splitLine: { show: false },
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
      name: 'Fuel',
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      data: gapped((p) => p.fuel_level_l),
      lineStyle: { width: 2, color: C.value.fuel },
      areaStyle: { color: C.value.fuelArea },
      markPoint: { data: markers.value },
    },
    {
      name: 'Fuel rate',
      type: 'line',
      xAxisIndex: 1,
      yAxisIndex: 1,
      showSymbol: false,
      connectNulls: false,
      data: gapped((p) => p.fuel_rate_lph),
      lineStyle: { width: 1.5, color: C.value.load },
      areaStyle: { color: C.value.loadArea },
    },
    {
      name: 'RPM',
      type: 'line',
      xAxisIndex: 1,
      yAxisIndex: 2,
      showSymbol: false,
      connectNulls: false,
      data: gapped((p) => p.rpm),
      lineStyle: { width: 1, type: 'dotted', color: C.value.text },
    },
  ],
}))

const summary = computed(() => {
  if (!props.points.length) return 'Tractor fuel chart, no readings in this window'
  const first = props.points[0]!
  const last = props.points[props.points.length - 1]!
  const losses = props.events.filter((e) => isFuelLoss(e.event_type)).length
  return [
    `Fuel level over ${props.points.length} points`,
    `from ${litres(first.fuel_level_l)} to ${litres(last.fuel_level_l)}`,
    losses ? `${losses} fuel loss event${losses > 1 ? 's' : ''}` : '',
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
  </div>
</template>

<style scoped>
.wrap { width: 100% }
.empty { padding: 40px 0; text-align: center; color: var(--ink-muted); font-size: 13px }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
</style>
