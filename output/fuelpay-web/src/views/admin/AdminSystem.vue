<script setup lang="ts">
/**
 * Is the simulator keeping up, is anything stuck, is the disk about to fill?
 * Plus the levers: run a tick, run the expiry job, retry a failed backfill,
 * and (owners) tune how often incidents happen across every tenant.
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Alert, App as AntApp, Button, InputNumber, Popconfirm, Progress, Table } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeading from '@/components/ui/SectionHeading.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import StatTile from '@/components/ui/StatTile.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { getSystem, getTuning, putTuning, retryBackfill, runExpiry, runTick } from '@/api/admin'
import type { SystemStatus, Tuning, TuningGroup } from '@/api/adminTypes'
import { ApiError } from '@/api/client'
import { bytes, dateTime, duration } from '@/lib/adminFormat'
import { useAdminAuthStore } from '@/stores/adminAuth'

const admin = useAdminAuthStore()
const { message } = AntApp.useApp()
const sys = ref<SystemStatus | null>(null)
const tuning = ref<Tuning | null>(null)
const error = ref<string | null>(null)
const busy = ref<string | null>(null)

async function load() {
  try {
    sys.value = await getSystem()
    error.value = null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load system status.'
  }
}
async function loadTuning() {
  tuning.value = await getTuning()
  draft.value = {
    theft: { ...(tuning.value.overrides.theft ?? {}) },
    vehicle: { ...(tuning.value.overrides.vehicle ?? {}) },
  }
}
let timer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  load()
  loadTuning()
  timer = setInterval(load, 10_000)
})
onBeforeUnmount(() => timer && clearInterval(timer))

const fail = (caught: unknown) =>
  message.error(caught instanceof ApiError ? caught.detail : 'That did not work.')

async function act(name: string, run: () => Promise<unknown>, done: (r: never) => string) {
  busy.value = name
  try {
    const result = await run()
    message.success(done(result as never))
    await load()
  } catch (caught) {
    fail(caught)
  } finally {
    busy.value = null
  }
}

const lagTone = computed(() => {
  const lag = sys.value?.max_lag_seconds
  if (lag === null || lag === undefined || !sys.value) return 'default'
  return lag > sys.value.tick_seconds * 6 ? 'critical' : lag > sys.value.tick_seconds * 2 ? 'watch' : 'ok'
})
const diskPct = computed(() =>
  sys.value ? 100 - (sys.value.disk_free_bytes / sys.value.disk_total_bytes) * 100 : 0,
)

const backfillColumns: TableColumnsType = [
  { title: 'Entity', key: 'name' },
  { title: 'Tenant', dataIndex: 'organisation', responsive: ['md'] },
  { title: 'Status', key: 'status', width: 200 },
  { title: '', key: 'actions', width: 90 },
]

// --- tuning ---
const draft = ref<{ theft: TuningGroup; vehicle: TuningGroup }>({ theft: {}, vehicle: {} })
const FIELDS: { group: 'theft' | 'vehicle'; key: string; label: string; step: number }[] = [
  { group: 'theft', key: 'probability_per_day', label: 'Site siphon chance / day', step: 0.005 },
  { group: 'theft', key: 'volume_min_fraction', label: 'Siphon size, min share of tank', step: 0.05 },
  { group: 'theft', key: 'volume_max_fraction', label: 'Siphon size, max share of tank', step: 0.05 },
  { group: 'theft', key: 'window_start_hour', label: 'Theft window starts (hour)', step: 1 },
  { group: 'theft', key: 'window_end_hour', label: 'Theft window ends (hour)', step: 1 },
  { group: 'vehicle', key: 'siphon_probability_per_day', label: 'Tractor siphon chance / day', step: 0.01 },
  { group: 'vehicle', key: 'return_line_probability', label: 'Return-line theft chance / day', step: 0.01 },
  { group: 'vehicle', key: 'short_fill_probability', label: 'Short fill chance / refuel', step: 0.01 },
  { group: 'vehicle', key: 'after_hours_probability', label: 'After-hours use chance / day', step: 0.01 },
  { group: 'vehicle', key: 'off_field_probability', label: 'Off-field detour chance / day', step: 0.01 },
  { group: 'vehicle', key: 'heavy_day_probability', label: 'Over-quota day chance', step: 0.01 },
]
const dirty = computed(() => {
  const saved = tuning.value?.overrides ?? {}
  return JSON.stringify({ theft: saved.theft ?? {}, vehicle: saved.vehicle ?? {} }) !== JSON.stringify(draft.value)
})
function setField(group: 'theft' | 'vehicle', key: string, value: number | null) {
  const next = { ...draft.value[group] }
  if (value === null || value === tuning.value?.defaults[group][key]) delete next[key]
  else next[key] = value
  draft.value = { ...draft.value, [group]: next }
}
async function saveTuning(reset = false) {
  busy.value = 'tuning'
  try {
    const overrides = reset
      ? {}
      : Object.fromEntries(Object.entries(draft.value).filter(([, v]) => Object.keys(v).length))
    tuning.value = await putTuning(overrides)
    await loadTuning()
    message.success(reset ? 'Back to defaults. Applies from the next tick.' : 'Saved. Applies from the next tick.')
  } catch (caught) {
    fail(caught)
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="System" :subtitle="sys ? `refreshed ${dateTime(sys.as_of)}` : undefined">
      <template #actions>
        <Button :loading="busy === 'tick'" @click="act('tick', runTick, (r: { readings: number; vehicle_readings: number }) => `Tick ran: ${r.readings + r.vehicle_readings} readings.`)">
          Run tick now
        </Button>
        <Popconfirm
          title="Revoke expired demos' keys and purge those past the grace period?"
          ok-text="Run expiry"
          @confirm="act('expire', runExpiry, (r: { keys_revoked: number; tenants_purged: number }) => `Revoked ${r.keys_revoked} key(s), purged ${r.tenants_purged} tenant(s).`)"
        >
          <Button :loading="busy === 'expire'">Run expiry now</Button>
        </Popconfirm>
      </template>
    </PageHeader>

    <Alert v-if="error" type="error" :message="error" show-icon class="mb" />
    <SkeletonBlock v-if="!sys && !error" height="300px" />

    <template v-else-if="sys">
      <Alert
        v-if="!sys.sim_enabled"
        type="warning"
        show-icon
        class="mb"
        message="The live simulator is switched off on this server (FUELPAY_SIM_ENABLED=false)."
      />
      <Alert
        v-if="diskPct > 92"
        type="error"
        show-icon
        class="mb"
        message="The API host's disk is nearly full"
        description="PostgreSQL fails writes and large sorts when the disk fills, which shows up as 500s on otherwise healthy endpoints."
      />

      <div class="tiles">
        <StatTile
          label="Simulator lag"
          :value="null"
          :display="duration(sys.max_lag_seconds)"
          :tone="lagTone"
          :sub="`tick every ${sys.tick_seconds} s`"
          emphasis="primary"
        />
        <StatTile
          label="Last tick (this server)"
          :value="null"
          :display="sys.last_tick ? dateTime(sys.last_tick.started_at) : '—'"
          :sub="sys.last_tick ? `${sys.last_tick.readings + sys.last_tick.vehicle_readings} readings · ${sys.last_tick.events} events` : 'none since start'"
        />
        <StatTile label="Database" :value="null" :display="bytes(sys.database_bytes)" sub="all tables and indexes" />
        <StatTile
          label="Disk free (API host)"
          :value="null"
          :display="bytes(sys.disk_free_bytes)"
          :tone="diskPct > 92 ? 'critical' : diskPct > 85 ? 'watch' : 'default'"
          :sub="`${diskPct.toFixed(0)}% of ${bytes(sys.disk_total_bytes)} used`"
        />
      </div>

      <div class="grid">
        <AppCard class="wide">
          <SectionHeading title="Backfills" :level="3" hint="demo entities still generating history, or failed" />
          <Table
            v-if="sys.backfills.length"
            :columns="backfillColumns"
            :data-source="sys.backfills"
            row-key="id"
            size="small"
            :pagination="false"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'name'">
                <div class="strong">{{ record.name }}</div>
                <div class="muted">{{ record.kind }}</div>
                <div v-if="record.error" class="err">{{ record.error }}</div>
              </template>
              <template v-else-if="column.key === 'status'">
                <StatusChip v-if="record.simulation_status === 'FAILED'" state="critical" label="Failed" size="sm" />
                <Progress v-else :percent="Math.round(record.progress * 100)" size="small" status="active" />
              </template>
              <template v-else-if="column.key === 'actions'">
                <Button size="small" :loading="busy === record.id" @click="act(record.id, () => retryBackfill(record.kind, record.id), () => 'Backfill queued.')">
                  Retry
                </Button>
              </template>
            </template>
          </Table>
          <EmptyState v-else title="Nothing generating, nothing stuck." />
        </AppCard>

        <AppCard>
          <SectionHeading title="Largest tables" :level="3" />
          <ul class="list">
            <li v-for="t in sys.tables" :key="t.name">
              <span class="mono">{{ t.name }}</span>
              <strong class="tabular">{{ bytes(t.bytes) }}</strong>
            </li>
          </ul>
        </AppCard>

        <AppCard class="span2">
          <SectionHeading title="Incident tuning" :level="3" :hint="admin.isOwner ? 'applies to every tenant from the next tick' : 'owners can change these'" />
          <template v-if="tuning">
            <div class="tuning">
              <label v-for="f in FIELDS" :key="f.group + f.key" class="tune">
                <span class="tune__label">
                  {{ f.label }}
                  <span v-if="draft[f.group][f.key] !== undefined" class="changed">changed</span>
                </span>
                <InputNumber
                  :value="draft[f.group][f.key] ?? tuning.defaults[f.group][f.key]"
                  :step="f.step"
                  :min="0"
                  :max="f.key.includes('hour') ? 23 : 1"
                  :disabled="!admin.isOwner"
                  style="width: 100%"
                  @update:value="(v: number | string | null) => setField(f.group, f.key, v === null ? null : Number(v))"
                />
                <span class="tune__default">default {{ tuning.defaults[f.group][f.key] }}</span>
              </label>
            </div>
            <div v-if="admin.isOwner" class="actions">
              <Button :disabled="!Object.keys(tuning.overrides).length" :loading="busy === 'tuning'" @click="saveTuning(true)">Reset to defaults</Button>
              <Button type="primary" :disabled="!dirty" :loading="busy === 'tuning'" @click="saveTuning()">Save tuning</Button>
            </div>
          </template>
        </AppCard>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 28px 28px 72px } }
.mb { margin-bottom: 14px }
.tiles { display: grid; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-bottom: 14px }
@media (min-width: 1024px) { .tiles { grid-template-columns: repeat(4, minmax(0, 1fr)) } }
.grid { display: grid; gap: 14px; grid-template-columns: 1fr }
@media (min-width: 1024px) {
  .grid { grid-template-columns: repeat(3, minmax(0, 1fr)) }
  .wide { grid-column: 1 / -1 }
  .span2 { grid-column: span 2 }
}
.strong { font-weight: 600 }
.muted { font-size: 12px; color: var(--ink-muted) }
.err { font-size: 12px; color: var(--status-critical-text) }
.mono { font-family: 'IBM Plex Mono', monospace; font-size: 12px }
.tabular { font-variant-numeric: tabular-nums; font-size: 13px }
.list { list-style: none; margin: 8px 0 0; padding: 0 }
.list li { display: flex; justify-content: space-between; gap: 10px; padding: 7px 0 }
.list li + li { border-top: 1px solid var(--hairline) }
.tuning { display: grid; gap: 12px 16px; grid-template-columns: 1fr; margin-top: 8px }
@media (min-width: 640px) { .tuning { grid-template-columns: 1fr 1fr } }
.tune { display: flex; flex-direction: column; gap: 4px }
.tune__label { font-size: 13px; font-weight: 600 }
.tune__default { font-size: 11px; color: var(--ink-subtle) }
.changed {
  margin-left: 6px; padding: 0 6px; border-radius: 999px; font-size: 10px; font-weight: 700;
  background: color-mix(in srgb, var(--accent) 25%, transparent); color: var(--ink);
}
.actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px }
</style>
