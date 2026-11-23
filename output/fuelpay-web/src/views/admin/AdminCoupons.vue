<script setup lang="ts">
/** PoC coupons: usage at a glance, and a drawer to mint a new one. */
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Alert, App as AntApp, Button, DatePicker, Drawer, Input, InputNumber, Table } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'
import type { Dayjs } from 'dayjs'

import PageHeader from '@/components/ui/PageHeader.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import { createCoupon, listCoupons } from '@/api/admin'
import type { Coupon } from '@/api/adminTypes'
import { ApiError } from '@/api/client'
import { date } from '@/lib/adminFormat'

const router = useRouter()
const { message } = AntApp.useApp()
const rows = ref<Coupon[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    rows.value = await listCoupons()
    error.value = null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load coupons.'
  } finally {
    loading.value = false
  }
}
onMounted(load)

type CouponState = { state: 'ok' | 'watch' | 'critical'; label: string }
function couponState(c: Coupon): CouponState {
  if (!c.is_active) return { state: 'critical', label: 'Off' }
  if (c.expires_at && new Date(c.expires_at) <= new Date()) return { state: 'critical', label: 'Expired' }
  if (c.redemptions_count >= c.max_redemptions) return { state: 'watch', label: 'Used up' }
  return { state: 'ok', label: 'Active' }
}

function signupLink(code: string) {
  return `${window.location.origin}/demo?code=${encodeURIComponent(code)}`
}
async function copyLink(code: string) {
  try {
    await navigator.clipboard.writeText(signupLink(code))
    message.success('Signup link copied.')
  } catch {
    message.info(signupLink(code))
  }
}

const columns: TableColumnsType = [
  { title: 'Code', key: 'code' },
  { title: 'Status', key: 'status', width: 100 },
  { title: 'Used', key: 'used', width: 160 },
  { title: 'Converted', dataIndex: 'conversions', width: 100, responsive: ['md'] },
  { title: 'Demo grants', key: 'grants', responsive: ['lg'] },
  { title: 'Code expires', key: 'expires', responsive: ['lg'] },
  { title: '', key: 'link', width: 110 },
]

// --- create ---
const drawer = ref(false)
const blank = () => ({
  code: '',
  label: '',
  max_redemptions: 5,
  demo_duration_days: 14,
  max_locations: 2,
  max_tractors: 2,
  max_generators_per_location: 3,
  expires_at: undefined as Dayjs | undefined,
})
const form = ref(blank())
const saving = ref(false)
const saveError = ref<string | null>(null)

async function submit() {
  saving.value = true
  saveError.value = null
  try {
    const { expires_at, code, label, ...limits } = form.value
    const created = await createCoupon({
      ...limits,
      code: code.trim() || undefined,
      label: label.trim() || undefined,
      expires_at: expires_at ? expires_at.endOf('day').toISOString() : null,
    })
    message.success(`Coupon ${created.code} created.`)
    drawer.value = false
    form.value = blank()
    load()
  } catch (caught) {
    saveError.value = caught instanceof ApiError ? caught.detail : 'Could not create the coupon.'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="page">
    <PageHeader title="Coupons" subtitle="PoC codes that open time-limited demo accounts">
      <template #actions>
        <Button type="primary" @click="drawer = true">New coupon</Button>
      </template>
    </PageHeader>

    <Alert v-if="error" type="error" :message="error" show-icon class="mb" />

    <Table
      :columns="columns"
      :data-source="rows"
      :loading="loading"
      row-key="id"
      size="middle"
      :pagination="{ pageSize: 25, hideOnSinglePage: true }"
      :custom-row="(row: Coupon) => ({ onClick: () => router.push({ name: 'admin-coupon', params: { id: row.id } }), class: 'clickable' })"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'code'">
          <RouterLink :to="{ name: 'admin-coupon', params: { id: record.id } }" class="code" @click.stop>
            {{ record.code }}
          </RouterLink>
          <div v-if="record.label" class="muted">{{ record.label }}</div>
        </template>
        <template v-else-if="column.key === 'status'">
          <StatusChip :state="couponState(record as Coupon).state" :label="couponState(record as Coupon).label" size="sm" />
        </template>
        <template v-else-if="column.key === 'used'">
          <div class="usage" :aria-label="`${record.redemptions_count} of ${record.max_redemptions} used`">
            <div class="bar"><span :style="{ width: `${Math.min(100, (record.redemptions_count / record.max_redemptions) * 100)}%` }" /></div>
            <span class="tabular">{{ record.redemptions_count }}/{{ record.max_redemptions }}</span>
          </div>
        </template>
        <template v-else-if="column.key === 'grants'">
          {{ record.demo_duration_days }} days · {{ record.max_locations }} loc · {{ record.max_tractors }} tractor
        </template>
        <template v-else-if="column.key === 'expires'">{{ record.expires_at ? date(record.expires_at) : 'never' }}</template>
        <template v-else-if="column.key === 'link'">
          <Button size="small" @click.stop="copyLink(record.code)">Copy link</Button>
        </template>
      </template>
    </Table>

    <Drawer :open="drawer" title="New coupon" :width="440" @close="drawer = false">
      <form class="form" @submit.prevent="submit">
        <label class="field">
          <span>Code <span class="opt">leave blank to generate</span></span>
          <Input v-model:value="form.code" placeholder="e.g. AGRIEXPO-26" class="code" />
        </label>
        <label class="field">
          <span>Label <span class="opt">who or what it's for</span></span>
          <Input v-model:value="form.label" placeholder="e.g. Kaduna agri expo leads" />
        </label>
        <div class="grid2">
          <label class="field">
            <span>Uses</span>
            <InputNumber v-model:value="form.max_redemptions" :min="1" :max="10000" style="width: 100%" />
          </label>
          <label class="field">
            <span>Code expires <span class="opt">optional</span></span>
            <DatePicker v-model:value="form.expires_at" style="width: 100%" />
          </label>
        </div>
        <fieldset class="fs">
          <legend>Each demo gets</legend>
          <div class="grid2">
            <label class="field">
              <span>Days</span>
              <InputNumber v-model:value="form.demo_duration_days" :min="1" :max="90" style="width: 100%" />
            </label>
            <label class="field">
              <span>Locations</span>
              <InputNumber v-model:value="form.max_locations" :min="0" :max="20" style="width: 100%" />
            </label>
            <label class="field">
              <span>Tractors</span>
              <InputNumber v-model:value="form.max_tractors" :min="0" :max="20" style="width: 100%" />
            </label>
            <label class="field">
              <span>Generators per location</span>
              <InputNumber v-model:value="form.max_generators_per_location" :min="1" :max="10" style="width: 100%" />
            </label>
          </div>
        </fieldset>
        <Alert v-if="saveError" type="error" :message="saveError" show-icon />
        <Button type="primary" html-type="submit" :loading="saving">Create coupon</Button>
      </form>
    </Drawer>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 28px 28px 72px } }
.mb { margin-bottom: 14px }
.code { font-family: var(--font-mono); font-weight: 600 }
.muted { font-size: 12px; color: var(--ink-muted) }
.usage { display: flex; align-items: center; gap: 8px }
.bar { flex: 1; height: 6px; border-radius: 3px; background: var(--surface-sunken); overflow: hidden; min-width: 60px }
.bar span { display: block; height: 100%; background: var(--accent) }
.tabular { font-variant-numeric: tabular-nums; font-size: 12px }
:deep(.clickable) { cursor: pointer }
.form { display: flex; flex-direction: column; gap: 14px }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 600 }
.opt { font-weight: 400; color: var(--ink-muted) }
.grid2 { display: grid; gap: 12px; grid-template-columns: 1fr 1fr }
.fs { border: 1px solid var(--hairline); border-radius: var(--radius-card); padding: 10px 12px 12px; margin: 0 }
.fs legend { font-size: 12px; font-weight: 600; color: var(--ink-muted); padding: 0 4px }
</style>
