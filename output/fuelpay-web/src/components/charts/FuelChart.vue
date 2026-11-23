<script setup lang="ts">
/**
 * Fuel level over time, with incidents called out on the trace.
 *
 * Two stacked panels sharing one x-axis rather than one chart with two y-axes.
 * Litres and kilowatts have no common scale, so a second axis would let the
 * reader infer crossings and relative magnitudes that do not exist — the most
 * common way a chart lies. Stacking keeps the time comparison and drops the
 * false one.
 *
 * Incidents are drawn three ways on purpose, because one is not enough:
 *   - a shaded band over the span, so a 20-minute siphon is visible even on a
 *     60-day view where it is a single pixel wide,
 *   - a labelled marker with the volume, so you get the number without hovering,
 *   - the band colour, which repeats the severity already in the feed.
 */
import { computed, ref } from 'vue'
import { useElementSize, useMediaQuery } from '@vueuse/core'
import VChart from 'vue-echarts'

import '@/plugins/echarts'
import type { SeriesPoint } from '@/api/series'
import type { Incident } from '@/lib/incidents'
import { isFuelLoss } from '@/lib/incidents'
import { chartTokens } from '@/theme/chart'
import { useTheme } from '@/composables/useTheme'
import { litres } from '@/lib/format'

const props = withDefaults(
  defineProps<{
    points: SeriesPoint[]
    incidents: Incident[]
    capacityL: number
    reorderThresholdPct: number
    bucketMinutes?: number
    height?: number
  }>(),
  { bucketMinutes: 5, height: 380 },
)

const thresholdL = computed(() => (props.capacityL * props.reorderThresholdPct) / 100)

const { resolved } = useTheme()
const C = computed(() => chartTokens(resolved.value))

const root = ref<HTMLElement>()
const { width } = useElementSize(root)
const narrow = computed(() => width.value > 0 && width.value < 480)
/** Touch devices: page scroll must always win over chart zoom. */
const coarse = useMediaQuery('(pointer: coarse)')

const AXIS_LINE = computed(() => ({ lineStyle: { color: C.value.axis } }))
const SPLIT_LINE = computed(() => ({ lineStyle: { color: C.value.split } }))

/**
 * Bands covering each incident's span.
 *
 * Widened to at least one bucket: a siphon shorter than the bucket would
 * otherwise collapse to a zero-width band and disappear at coarse zoom, which
 * is exactly when you most need to spot it.
 */
const incidentBands = computed(() =>
  props.incidents
    .filter((incident) => incident.event_type !== 'LOW_FUEL')
    .map((incident) => {
      const from = new Date(incident.occurred_at).getTime()
      const to = new Date(incident.ended_at).getTime()
      const minWidth = props.bucketMinutes * 60_000
      const end = Math.max(to, from + minWidth)
      const loss = isFuelLoss(incident.event_type)
      return [
        {
          xAxis: from,
          itemStyle: { color: loss ? C.value.bandDrain : C.value.bandRefill },
        },
        { xAxis: end },
      ]
    }),
)

const incidentMarkers = computed(() =>
  props.incidents.map((incident) => {
    const drain = isFuelLoss(incident.event_type)
    const low = incident.event_type === 'LOW_FUEL'
    const colour = drain ? C.value.critical : low ? C.value.watch : C.value.ok
    return {
      name: incident.event_type,
      value: incident.volume_l ? litres(Math.abs(incident.volume_l)) : '',
      xAxis: new Date(incident.occurred_at).getTime(),
      yAxis: incident.fuel_level_l ?? 0,
      symbol: drain ? 'triangle' : low ? 'diamond' : 'arrow',
      symbolRotate: drain ? 180 : 0,
      symbolSize: drain ? 13 : 11,
      // The halo must be the SURFACE, not white — a white ring on a dark card
      // is the most visible dark-mode defect on this screen.
      itemStyle: { color: colour, borderColor: C.value.markHalo, borderWidth: 1.5 },
      label: {
        show: Boolean(incident.volume_l),
        position: drain ? 'bottom' : 'top',
        distance: 6,
        color: colour,
        fontSize: 11,
        fontWeight: 600,
        formatter: () =>
          `${drain ? '−' : '+'}${litres(Math.abs(incident.volume_l ?? 0))}`,
      },
    }
  }),
)

const levelData = computed(() =>
  props.points.map((point) => [new Date(point.time).getTime(), point.fuel_level_l]),
)

/**
 * The per-bucket minimum, drawn faintly under the mean.
 *
 * At one point per hour a 20-minute siphon barely moves the mean. The minimum
 * keeps the cliff at its true depth, so the shape of an incident survives
 * downsampling instead of being smoothed into a gentle slope.
 */
const minData = computed(() =>
  props.points.map((point) => [new Date(point.time).getTime(), point.fuel_min_l]),
)

const loadData = computed(() =>
  props.points.map((point) => [new Date(point.time).getTime(), point.load_kw]),
)

/**
 * A sentence describing the chart, for the wrapper's aria-label.
 *
 * An ECharts canvas is completely invisible to assistive tech and cannot carry
 * a text alternative of its own, so both this and the table below exist.
 */
const summary = computed(() => {
  if (!props.points.length) return 'Fuel level chart, no readings in this window'
  const first = props.points[0]!
  const last = props.points[props.points.length - 1]!
  const drains = props.incidents.filter((i) => isFuelLoss(i.event_type)).length
  const refills = props.incidents.filter((i) =>
    ['REFILL', 'DELIVERY', 'TRANSFER'].includes(i.event_type),
  ).length
  return [
    `Fuel level over ${props.points.length} points`,
    `from ${litres(first.fuel_level_l)} to ${litres(last.fuel_level_l)}`,
    `reorder threshold ${litres(thresholdL.value)}`,
    // "unexplained loss" rather than "drain": a short delivery or a loss across
    // a sensor gap counts here too, and neither is established theft.
    drains ? `${drains} unexplained loss${drains > 1 ? 'es' : ''}` : '',
    refills ? `${refills} replenishment${refills > 1 ? 's' : ''}` : '',
  ]
    .filter(Boolean)
    .join(', ')
})

/** Downsampled to ~30 rows: a table of 600 is not an accessibility feature. */
const tableRows = computed(() => {
  const step = Math.max(1, Math.ceil(props.points.length / 30))
  return props.points
    .filter((_, index) => index % step === 0)
    .map((point) => ({
      time: new Date(point.time).toLocaleString(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      }),
      fuel: litres(point.fuel_level_l),
      min: litres(point.fuel_min_l),
      load: `${point.load_kw.toFixed(1)} kW`,
    }))
})

const option = computed(() => ({
  animation: false,
  backgroundColor: 'transparent',
  tooltip: {
    trigger: 'axis',
    axisPointer: { type: 'cross', label: { backgroundColor: C.value.text } },
    backgroundColor: C.value.tooltipBg,
    borderColor: C.value.tooltipBorder,
    textStyle: { fontSize: 12, color: C.value.textStrong },
  },
  // One pointer line spanning both panels, so a moment in the level chart and
  // the same moment in the load chart are read together.
  axisPointer: { link: [{ xAxisIndex: 'all' }] },
  legend: {
    data: ['Fuel level', 'Bucket low', 'Load'],
    top: 0,
    right: 0,
    icon: 'roundRect',
    itemWidth: 10,
    itemHeight: 10,
    textStyle: { color: C.value.text, fontSize: 11 },
  },
  // 56px of a 360px screen is 15% of the width, so the gutter shrinks and the
  // axis labels abbreviate on narrow viewports.
  grid: [
    { left: narrow.value ? 40 : 56, right: narrow.value ? 12 : 20, top: 34, height: '50%' },
    { left: narrow.value ? 40 : 56, right: narrow.value ? 12 : 20, top: '70%', height: '17%' },
  ],
  xAxis: [
    {
      type: 'time',
      gridIndex: 0,
      axisLine: AXIS_LINE.value,
      axisLabel: { show: false },
      splitLine: SPLIT_LINE.value,
    },
    {
      type: 'time',
      gridIndex: 1,
      axisLine: AXIS_LINE.value,
      axisLabel: { color: C.value.text, fontSize: 11 },
      splitLine: SPLIT_LINE.value,
    },
  ],
  yAxis: [
    {
      type: 'value',
      gridIndex: 0,
      name: 'Litres',
      nameTextStyle: { color: C.value.text, fontSize: 11, align: 'right' },
      min: 0,
      max: Math.ceil(props.capacityL / 50) * 50,
      axisLine: AXIS_LINE.value,
      axisLabel: {
        color: C.value.text,
        fontSize: 11,
        formatter: (v: number) => (narrow.value && v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(v)),
      },
      splitLine: SPLIT_LINE.value,
    },
    {
      type: 'value',
      gridIndex: 1,
      name: 'kW',
      nameTextStyle: { color: C.value.text, fontSize: 11, align: 'right' },
      min: 0,
      axisLine: AXIS_LINE.value,
      axisLabel: { color: C.value.text, fontSize: 11 },
      splitLine: SPLIT_LINE.value,
    },
  ],
  dataZoom: [
    // Disabled on touch: an inside-zoom competes with page scroll, and the
    // page must always win. The slider stays as the range control.
    { type: 'inside', xAxisIndex: [0, 1], disabled: coarse.value, zoomOnMouseWheel: 'ctrl' },
    {
      type: 'slider',
      xAxisIndex: [0, 1],
      bottom: 6,
      // 22px rather than 18: on touch this is the only range control, so the
      // thumb needs to be grabbable.
      height: 22,
      borderColor: C.value.tooltipBorder,
      fillerColor: C.value.zoomFill,
    },
  ],
  series: [
    {
      name: 'Bucket low',
      type: 'line',
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: minData.value,
      showSymbol: false,
      itemStyle: { color: C.value.fuel },
      lineStyle: { width: 1, color: C.value.fuel, opacity: 0.45, type: 'dotted' },
      sampling: 'lttb',
      z: 2,
    },
    {
      name: 'Fuel level',
      type: 'line',
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: levelData.value,
      showSymbol: false,
      smooth: false,
      // LTTB keeps the peaks and troughs that define a refill or a siphon;
      // naive decimation drops exactly the points that matter here.
      sampling: 'lttb',
      itemStyle: { color: C.value.fuel },
      lineStyle: { width: 2, color: C.value.fuel },
      areaStyle: { color: C.value.fuelArea },
      z: 3,
      markLine: {
        silent: true,
        symbol: 'none',
        data: [
          {
            yAxis: thresholdL.value,
            lineStyle: { color: C.value.watch, type: 'dashed', width: 1.4 },
            label: {
              formatter: `Reorder ${props.reorderThresholdPct}%`,
              // Left-anchored on purpose: incidents cluster at the right-hand
              // (recent) edge, and an end-anchored label collided with their
              // volume markers.
              position: 'insideStartTop',
              color: C.value.watch,
              fontSize: 11,
            },
          },
        ],
      },
      markArea: { silent: true, data: incidentBands.value },
      markPoint: { silent: true, symbolSize: 12, data: incidentMarkers.value },
    },
    {
      name: 'Load',
      type: 'line',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: loadData.value,
      showSymbol: false,
      sampling: 'lttb',
      step: 'end',
      itemStyle: { color: C.value.load },
      lineStyle: { width: 1.4, color: C.value.load },
      areaStyle: { color: C.value.loadArea },
    },
  ],
}))
</script>

<template>
  <div ref="root" role="img" :aria-label="summary">
    <VChart
      v-if="points.length"
      :key="resolved"
      :option="option"
      class="chart"
      autoresize
    />
    <p v-else class="empty">No readings in this window.</p>

    <!-- The canvas is invisible to assistive tech and cannot carry a text
         alternative, so the numbers are also available as a real table. -->
    <details v-if="points.length" class="table-fallback">
      <summary>View as table</summary>
      <div class="scroll">
        <table>
          <caption class="sr-only">{{ summary }}</caption>
          <thead>
            <tr><th scope="col">Time</th><th scope="col">Fuel</th><th scope="col">Low</th><th scope="col">Load</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in tableRows" :key="row.time">
              <td>{{ row.time }}</td>
              <td class="tabular">{{ row.fuel }}</td>
              <td class="tabular">{{ row.min }}</td>
              <td class="tabular">{{ row.load }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  </div>
</template>

<style scoped>
.chart {
  width: 100%;
  /* Was a fixed 380px, which left the load panel about 60px tall on a phone. */
  height: clamp(280px, 46vh, 420px);
}
.empty {
  display: flex;
  align-items: center;
  justify-content: center;
  height: clamp(220px, 30vh, 320px);
  margin: 0;
  font-size: 14px;
  color: var(--ink-muted);
}
.table-fallback {
  margin-top: 10px;
  font-size: 13px;
}
.table-fallback summary {
  cursor: pointer;
  color: var(--ink-muted);
  padding: 6px 2px;
  min-height: 32px;
}
.table-fallback summary:hover { color: var(--ink) }
.scroll { overflow-x: auto; margin-top: 8px }
table { border-collapse: collapse; width: 100%; font-size: 12.5px }
th, td { text-align: left; padding: 5px 10px; border-bottom: 1px solid var(--hairline); white-space: nowrap }
th { color: var(--ink-muted); font-weight: 600 }
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}
</style>
