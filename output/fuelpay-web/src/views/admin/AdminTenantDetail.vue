<script setup lang="ts">
/**
 * One tenant: what it monitors, its keys, and — for a demo — the levers sales
 * needs (extend, convert). Purge sits in a danger zone behind a typed-name
 * confirmation, because it deletes every reading the tenant ever produced.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Alert, App as AntApp, Button, Input, InputNumber, Modal, Table } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeading from '@/components/ui/SectionHeading.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import DataList from '@/components/ui/DataList.vue'
import DataListItem from '@/components/ui/DataListItem.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import KeyReveal from '@/components/admin/KeyReveal.vue'
import {
  convertDemo,
  extendDemo,
  getTenant,
  issueKey,
  purgeTenant,
  retryBackfill,
  revokeKey,
} from '@/api/admin'
import type { IssuedKey, TenantDetail, TenantKind } from '@/api/adminTypes'
import { ApiError } from '@/api/client'
import type { StreamStatus } from '@/api/types'
import { KIND_LABEL, KIND_STATE, date, dateTime, untilText } from '@/lib/adminFormat'
import { relativeTime } from '@/lib/format'
import { useAdminAuthStore } from '@/stores/adminAuth'

const props = defineProps<{ id: string }>()
const router = useRouter()
const admin = useAdminAuthStore()
const { message } = AntApp.useApp()

const tenant = ref<TenantDetail | null>(null)
const error = ref<string | null>(null)
const busy = ref<string | null>(null)

async function load() {
  try {
    tenant.value = await getTenant(props.id)
    document.title = `${tenant.value.name} · Admin`
    error.value = null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load the tenant.'
  }
}
onMounted(load)
watch(() => props.id, load)

const fail = (caught: unknown) =>
  message.error(caught instanceof ApiError ? caught.detail : 'That did not work.')

async function act(name: string, run: () => Promise<unknown>, done: string) {
  busy.value = name
  try {
    await run()
    message.success(done)
    await load()
  } catch (caught) {
    fail(caught)
  } finally {
    busy.value = null
  }
}

const isDemo = computed(() => tenant.value?.kind !== 'real')
const extendDays = ref(7)

// --- keys ---
const keyLabel = ref('')
const issued = ref<IssuedKey | null>(null)
async function newKey() {
  if (!tenant.value) return
  busy.value = 'key'
  try {
    issued.value = await issueKey(tenant.value.id, keyLabel.value.trim() || 'default')
    keyLabel.value = ''
    await load()
  } catch (caught) {
    fail(caught)
  } finally {
    busy.value = null
  }
}

// --- purge ---
const purgeOpen = ref(false)
const purgeName = ref('')
const canPurge = computed(() => isDemo.value || admin.isOwner)
async function purge() {
  if (!tenant.value) return
  busy.value = 'purge'
  try {
    await purgeTenant(tenant.value.id, purgeName.value)
    message.success(`${tenant.value.name} and all its data were deleted.`)
    router.push({ name: 'admin-tenants' })
  } catch (caught) {
    fail(caught)
  } finally {
    busy.value = null
  }
}

const STREAM: Record<StreamStatus, { state: 'ok' | 'watch' | 'critical'; label: string }> = {
  LIVE: { state: 'ok', label: 'Live' },
  PENDING: { state: 'watch', label: 'Queued' },
  BACKFILLING: { state: 'watch', label: 'Generating' },
  FAILED: { state: 'critical', label: 'Failed' },
}

const keyColumns: TableColumnsType = [
  { title: 'Key', key: 'prefix' },
  { title: 'Label', dataIndex: 'label' },
  { title: 'Created', key: 'created', responsive: ['md'] },
  { title: 'Status', key: 'status' },
  { title: '', key: 'actions', width: 90 },
]
</script>

<template>
  <div class="page">
    <SkeletonBlock v-if="!tenant && !error" height="320px" />
    <Alert v-else-if="error && !tenant" type="error" :message="error" show-icon />

    <template v-else-if="tenant">
      <PageHeader :title="tenant.name" :subtitle="tenant.slug" back-to="/admin/tenants" back-label="Tenants">
        <template #actions>
          <StatusChip :state="KIND_STATE[tenant.kind as TenantKind]" :label="KIND_LABEL[tenant.kind as TenantKind]" />
        </template>
      </PageHeader>

      <div class="layout">
        <div class="stack">
          <AppCard>
            <DataList>
              <DataListItem label="Created">{{ date(tenant.created_at) }}</DataListItem>
              <DataListItem label="Last data">
                {{ tenant.last_reading_at ? relativeTime(tenant.last_reading_at) : 'none in 2 days' }}
              </DataListItem>
              <DataListItem v-if="tenant.coupon_code" label="Coupon">
                <RouterLink :to="{ name: 'admin-coupons' }" class="mono">{{ tenant.coupon_code }}</RouterLink>
              </DataListItem>
              <DataListItem v-if="tenant.contact_email" label="Contact">{{ tenant.contact_email }}</DataListItem>
              <DataListItem v-if="isDemo" label="Demo ends">
                {{ dateTime(tenant.demo_expires_at) }} ({{ untilText(tenant.demo_expires_at) }})
              </DataListItem>
              <DataListItem v-if="tenant.converted_at" label="Converted">{{ date(tenant.converted_at) }}</DataListItem>
            </DataList>
          </AppCard>

          <AppCard v-if="isDemo">
            <SectionHeading title="Demo" :level="3" />
            <p class="note">
              {{ tenant.kind === 'expired'
                ? 'This demo has expired. Its key stopped working; its data is purged 24 hours after expiry unless you extend or convert it.'
                : 'Extend to give the prospect more time, or convert when they sign — all their data is kept.' }}
            </p>
            <div class="actions">
              <InputNumber v-model:value="extendDays" :min="1" :max="90" addon-after="days" style="width: 140px" />
              <Button :loading="busy === 'extend'" @click="act('extend', () => extendDemo(tenant!.id, extendDays), `Extended by ${extendDays} days.`)">
                Extend
              </Button>
              <Button type="primary" :loading="busy === 'convert'" @click="act('convert', () => convertDemo(tenant!.id), 'Converted to a customer.')">
                Convert to customer
              </Button>
            </div>
          </AppCard>

          <AppCard>
            <SectionHeading title="API keys" :level="3" :hint="`${tenant.active_keys} active`" />
            <KeyReveal v-if="issued" :api-key="issued.api_key" class="mb" />
            <Table
              :columns="keyColumns"
              :data-source="tenant.keys"
              row-key="id"
              size="small"
              :pagination="false"
              :scroll="{ x: 'max-content' }"
            >
              <template #bodyCell="{ column, record }">
                <span v-if="column.key === 'prefix'" class="mono">{{ record.prefix }}…</span>
                <template v-else-if="column.key === 'created'">{{ date(record.created_at) }}</template>
                <template v-else-if="column.key === 'status'">
                  <StatusChip v-if="record.revoked_at" state="critical" label="Revoked" size="sm" />
                  <StatusChip v-else state="ok" label="Active" size="sm" />
                </template>
                <template v-else-if="column.key === 'actions'">
                  <Button
                    v-if="!record.revoked_at"
                    size="small"
                    danger
                    :loading="busy === record.id"
                    @click="act(record.id, () => revokeKey(tenant!.id, record.id), 'Key revoked.')"
                    >Revoke</Button
                  >
                </template>
              </template>
            </Table>
            <form class="actions mt" @submit.prevent="newKey">
              <Input v-model:value="keyLabel" placeholder="Label, e.g. scada-gateway" style="max-width: 240px" />
              <Button html-type="submit" :loading="busy === 'key'">Issue key</Button>
            </form>
          </AppCard>
        </div>

        <div class="stack">
          <AppCard>
            <SectionHeading title="Locations" :level="3" :hint="`${tenant.site_list.length}`" />
            <ul v-if="tenant.site_list.length" class="list">
              <li v-for="site in tenant.site_list" :key="site.id">
                <div>
                  <div class="strong">{{ site.name }}</div>
                  <div class="muted">{{ site.profile.replace('_', ' ').toLowerCase() }} · {{ site.generators }} generator(s)</div>
                  <div v-if="site.backfill_error" class="err">{{ site.backfill_error }}</div>
                </div>
                <div class="right">
                  <StatusChip :state="STREAM[site.simulation_status].state" :label="STREAM[site.simulation_status].label" size="sm" />
                  <Button
                    v-if="site.simulation_status === 'FAILED'"
                    size="small"
                    @click="act(site.id, () => retryBackfill('location', site.id), 'Backfill queued.')"
                    >Retry</Button
                  >
                </div>
              </li>
            </ul>
            <EmptyState v-else title="No locations." />
          </AppCard>

          <AppCard>
            <SectionHeading title="Tractors" :level="3" :hint="`${tenant.vehicle_list.length}`" />
            <ul v-if="tenant.vehicle_list.length" class="list">
              <li v-for="v in tenant.vehicle_list" :key="v.id">
                <div>
                  <div class="strong">{{ v.name }}</div>
                  <div class="muted">
                    {{ v.serial }} · {{ v.last_seen_at ? `seen ${relativeTime(v.last_seen_at)}` : 'not reporting' }}
                  </div>
                  <div v-if="v.backfill_error" class="err">{{ v.backfill_error }}</div>
                </div>
                <div class="right">
                  <StatusChip :state="STREAM[v.simulation_status].state" :label="STREAM[v.simulation_status].label" size="sm" />
                  <Button
                    v-if="v.simulation_status === 'FAILED'"
                    size="small"
                    @click="act(v.id, () => retryBackfill('tractor', v.id), 'Backfill queued.')"
                    >Retry</Button
                  >
                </div>
              </li>
            </ul>
            <EmptyState v-else title="No tractors." />
          </AppCard>

          <AppCard class="danger">
            <SectionHeading title="Danger zone" :level="3" />
            <p class="note">
              Purging deletes this tenant, its keys, and every reading and event it has ever produced.
              It cannot be undone.
              <template v-if="!canPurge"><br />Only owners can purge a customer.</template>
            </p>
            <Button danger :disabled="!canPurge" @click="purgeOpen = true">Purge tenant…</Button>
          </AppCard>
        </div>
      </div>

      <Modal
        :open="purgeOpen"
        title="Purge tenant"
        ok-text="Purge permanently"
        :ok-button-props="{ danger: true, disabled: purgeName !== tenant.name, loading: busy === 'purge' }"
        @ok="purge"
        @cancel="purgeOpen = false; purgeName = ''"
      >
        <p>Type <strong>{{ tenant.name }}</strong> to confirm.</p>
        <Input v-model:value="purgeName" :placeholder="tenant.name" aria-label="Tenant name to confirm" />
      </Modal>
    </template>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 28px 28px 72px } }
.layout { display: grid; gap: 14px; grid-template-columns: 1fr }
@media (min-width: 1100px) { .layout { grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) } }
.stack { display: flex; flex-direction: column; gap: 14px; min-width: 0 }
.note { margin: 6px 0 12px; font-size: 13px; color: var(--ink-muted) }
.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center }
.mt { margin-top: 12px }
.mb { margin-bottom: 12px }
.mono { font-family: 'IBM Plex Mono', monospace; font-size: 12px }
.list { list-style: none; margin: 6px 0 0; padding: 0 }
.list li { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0 }
.list li + li { border-top: 1px solid var(--hairline) }
.strong { font-weight: 600; font-size: 14px }
.muted { font-size: 12px; color: var(--ink-muted) }
.err { font-size: 12px; color: var(--status-critical-text) }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; flex: none }
.danger { border-color: color-mix(in srgb, var(--status-critical) 40%, var(--hairline)) }
</style>
