<script setup lang="ts">
/** The platform at a glance: tenants, the demo funnel, data flow, incidents. */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Alert } from 'ant-design-vue'
import VChart from 'vue-echarts'

import '@/plugins/echarts'
import AppCard from '@/components/ui/AppCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeading from '@/components/ui/SectionHeading.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import StatTile from '@/components/ui/StatTile.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { getOverview } from '@/api/admin'
import type { Overview } from '@/api/adminTypes'
import type { EventType } from '@/api/types'
import { EVENT_SPEC } from '@/lib/incidents'
import { chartTokens } from '@/theme/chart'
import { useTheme } from '@/composables/useTheme'
import { dateTime } from '@/lib/adminFormat'

const data = ref<Overview | null>(null)
const error = ref<string | null>(null)

async function load() {
  try {
    data.value = await getOverview()
    error.value = null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load the overview.'
  }
}
let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  load()
  timer = setInterval(load, 60_000)
})
onBeforeUnmount(() => timer && clearInterval(timer))

const { resolved } = useTheme()
const C = computed(() => chartTokens(resolved.value))
const option = computed(() => ({
  animation: false,
  grid: { left: 36, right: 12, top: 16, bottom: 28 },
  tooltip: {
    trigger: 'axis',
    backgroundColor: C.value.tooltipBg,
    borderColor: C.value.tooltipBorder,
    textStyle: { color: C.value.textStrong },
  },
  xAxis: {
    type: 'category',
    data: data.value?.redemptions_by_day.map((d) =>
      new Date(d.day).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }),
    ),
    axisLine: { lineStyle: { color: C.value.axis } },
    axisLabel: { color: C.value.text },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLabel: { color: C.value.text },
    splitLine: { lineStyle: { color: C.value.split } },
  },
  series: [
    {
      name: 'Demo signups',
      type: 'bar',
      data: data.value?.redemptions_by_day.map((d) => d.count),
      itemStyle: { color: C.value.fuel, borderRadius: [3, 3, 0, 0] },
      barMaxWidth: 18,
    },
  ],
}))

const label = (type: string) => EVENT_SPEC[type as EventType]?.label ?? type
const conversion = computed(() =>
  data.value?.conversion_rate === null || data.value?.conversion_rate === undefined
    ? '—'
    : `${(data.value.conversion_rate * 100).toFixed(0)}%`,
)
</script>

<template>
  <div class="page">
    <PageHeader title="Overview" :subtitle="data ? `as of ${dateTime(data.as_of)}` : undefined" />
    <Alert v-if="error" type="error" :message="error" show-icon class="mb" />

    <template v-if="!data && !error">
      <SkeletonBlock height="100px" />
      <SkeletonBlock height="280px" class="mt" />
    </template>

    <template v-else-if="data">
      <div class="tiles">
        <StatTile label="Customers" :value="data.tenants_real" sub="paying tenants" emphasis="primary" />
        <StatTile
          label="Active demos"
          :value="data.demos_active"
          :sub="`${data.demos_expiring_3d} ending within 3 days`"
          :tone="data.demos_expiring_3d ? 'watch' : 'default'"
        />
        <StatTile
          label="Conversion"
          :value="null"
          :display="conversion"
          :sub="`${data.conversions_30d} of ${data.redemptions_30d} demos, 30 days`"
        />
        <StatTile label="Readings, 24 h" :value="data.readings_24h" sub="generators, tanks, tractors" />
      </div>

      <div class="grid">
        <AppCard class="wide">
          <SectionHeading title="Demo signups" hint="coupon redemptions per day, last 30 days" />
          <VChart :option="option" style="height: 240px" autoresize aria-label="Demo signups per day" />
        </AppCard>

        <AppCard>
          <SectionHeading title="Incidents, 24 h" :level="3" />
          <ul v-if="data.incidents_24h.length" class="list">
            <li v-for="row in data.incidents_24h" :key="row.event_type">
              <span>{{ label(row.event_type) }}</span>
              <strong class="tabular">{{ row.count }}</strong>
            </li>
          </ul>
          <EmptyState v-else title="No incidents in the last day." />
        </AppCard>

        <AppCard>
          <SectionHeading title="Most incidents, 24 h" :level="3" hint="by tenant" />
          <ul v-if="data.incidents_by_tenant_24h.length" class="list">
            <li v-for="row in data.incidents_by_tenant_24h" :key="row.organisation_id">
              <RouterLink :to="{ name: 'admin-tenant', params: { id: row.organisation_id } }">{{ row.name }}</RouterLink>
              <strong class="tabular">{{ row.count }}</strong>
            </li>
          </ul>
          <EmptyState v-else title="Quiet across every tenant." />
        </AppCard>

        <AppCard>
          <SectionHeading title="Demos" :level="3" />
          <ul class="list">
            <li><span>Active</span><strong class="tabular">{{ data.demos_active }}</strong></li>
            <li><span>Ending within 3 days</span><strong class="tabular">{{ data.demos_expiring_3d }}</strong></li>
            <li><span>Expired, awaiting purge</span><strong class="tabular">{{ data.demos_expired }}</strong></li>
          </ul>
          <RouterLink :to="{ name: 'admin-tenants', query: { kind: 'demo' } }" class="more">All demos →</RouterLink>
        </AppCard>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 28px 28px 72px } }
.mb { margin-bottom: 14px }
.mt { margin-top: 14px }
.tiles { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 14px }
@media (min-width: 1024px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)) } }
.grid { display: grid; gap: 14px; grid-template-columns: 1fr }
@media (min-width: 1024px) {
  .grid { grid-template-columns: repeat(3, minmax(0, 1fr)) }
  .wide { grid-column: 1 / -1 }
}
.list { list-style: none; margin: 8px 0 0; padding: 0 }
.list li { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0; font-size: 13px }
.list li + li { border-top: 1px solid var(--hairline) }
.tabular { font-variant-numeric: tabular-nums }
.more { display: inline-block; margin-top: 10px; font-size: 13px }
</style>
