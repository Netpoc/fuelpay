<script setup lang="ts">
/**
 * Where a site's fuel went, by day.
 *
 * The two loss series share the critical hue and are separated by a diagonal
 * decal rather than a fourth colour: the palette is capped at three hues for
 * colourblind validation, and a decal survives greyscale and every CVD type. A
 * suspected drain and an unverified loss are different claims and must stay
 * visually distinct — one was observed, the other is fuel missing across an
 * outage nobody watched.
 */
import { computed } from 'vue'
import VChart from 'vue-echarts'
import dayjs from 'dayjs'

import '@/plugins/echarts'
import { useTheme } from '@/composables/useTheme'
import { chartTokens } from '@/theme/chart'
import { litres } from '@/lib/format'
import type { SiteFlowDay } from '@/lib/siteFlow'

const props = defineProps<{ days: SiteFlowDay[]; height?: number }>()

const { resolved } = useTheme()
const tokens = computed(() => chartTokens(resolved.value))

const labels = computed(() => props.days.map((day) => dayjs(day.day).format('D MMM')))

/**
 * An unobserved day is a HOLE, not a zero.
 *
 * Returning null leaves no bar at all, which is the bar-chart equivalent of
 * breaking a line across a sensor gap. A zero would assert that no fuel moved
 * on a day when nothing was watching.
 */
const series = (key: keyof SiteFlowDay) =>
  props.days.map((day) => (day.unobserved ? null : (day[key] as number)))

const option = computed(() => {
  const t = tokens.value
  const decal = {
    color: 'rgba(255,255,255,0.45)',
    dashArrayX: [1, 0],
    dashArrayY: [3, 4],
    rotation: -Math.PI / 4,
  }

  return {
    animation: false,
    grid: { left: 8, right: 8, top: 30, bottom: 4, containLabel: true },
    legend: {
      top: 0,
      itemHeight: 9,
      itemWidth: 14,
      textStyle: { color: t.text, fontSize: 11 },
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: t.tooltipBg,
      borderColor: t.tooltipBorder,
      textStyle: { color: t.textStrong, fontSize: 12 },
      formatter: (params: { dataIndex: number }[]) => {
        const day = props.days[params[0]?.dataIndex ?? 0]
        if (!day) return ''
        if (day.unobserved) {
          return `<strong>${dayjs(day.day).format('D MMM')}</strong><br/>No readings — nothing was observed.`
        }
        const rows = [
          ['Burned', day.consumed_l],
          ['Delivered', day.delivered_l],
          ['Bulk → day', day.transferred_l],
          ['Drained', day.drained_l],
          ['Unverified loss', day.unverified_loss_l],
        ]
          .filter(([, value]) => (value as number) > 0)
          .map(([label, value]) => `${label}: ${litres(value as number)}`)
          .join('<br/>')
        const partial =
          day.coverage < 0.9
            ? `<br/><em>${Math.round(day.coverage * 100)}% of readings — a floor, not the total.</em>`
            : ''
        return `<strong>${dayjs(day.day).format('D MMM')}</strong><br/>${rows || 'No movement'}${partial}`
      },
    },
    xAxis: {
      type: 'category',
      data: labels.value,
      axisLine: { lineStyle: { color: t.axis } },
      axisTick: { show: false },
      axisLabel: { color: t.text, fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      name: 'litres',
      nameTextStyle: { color: t.text, fontSize: 10, align: 'left' },
      splitLine: { lineStyle: { color: t.split } },
      axisLabel: { color: t.text, fontSize: 10 },
    },
    series: [
      {
        name: 'Burned',
        type: 'bar',
        stack: 'out',
        data: series('consumed_l'),
        itemStyle: { color: t.fuel },
      },
      {
        name: 'Drained',
        type: 'bar',
        stack: 'out',
        data: series('drained_l'),
        itemStyle: { color: t.critical },
      },
      {
        name: 'Unverified loss',
        type: 'bar',
        stack: 'out',
        data: series('unverified_loss_l'),
        itemStyle: { color: t.critical, decal },
      },
      {
        name: 'Delivered',
        type: 'bar',
        stack: 'in',
        data: series('delivered_l'),
        itemStyle: { color: t.ok },
      },
      {
        name: 'Bulk → day',
        type: 'bar',
        stack: 'in',
        data: series('transferred_l'),
        itemStyle: { color: t.load },
      },
    ],
  }
})
</script>

<template>
  <VChart
    class="chart"
    :option="option"
    :style="{ height: `${height ?? 260}px` }"
    autoresize
    role="img"
    aria-label="Daily fuel movement at this site"
  />
</template>

<style scoped>
.chart { width: 100% }
</style>
