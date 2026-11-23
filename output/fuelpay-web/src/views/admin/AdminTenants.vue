<script setup lang="ts">
/** Every organisation on the platform, filterable, plus "new customer". */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Alert, Button, Drawer, Input, Table } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import PageHeader from '@/components/ui/PageHeader.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import StatusChip from '@/components/ui/StatusChip.vue'
import KeyReveal from '@/components/admin/KeyReveal.vue'
import { createTenant, listTenants } from '@/api/admin'
import type { IssuedKey, TenantKind, TenantRow } from '@/api/adminTypes'
import { ApiError } from '@/api/client'
import { KIND_LABEL, KIND_STATE, date, untilText } from '@/lib/adminFormat'
import { relativeTime } from '@/lib/format'

const route = useRoute()
const router = useRouter()

const KINDS = [
  { label: 'All', value: 'all' },
  { label: 'Customers', value: 'real' },
  { label: 'Demos', value: 'demo' },
  { label: 'Expired', value: 'expired' },
]
const kind = ref<string>(typeof route.query.kind === 'string' ? route.query.kind : 'all')
const q = ref('')
const rows = ref<TenantRow[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    rows.value = await listTenants({
      kind: kind.value === 'all' ? undefined : (kind.value as TenantKind),
      q: q.value.trim() || undefined,
    })
    error.value = null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load tenants.'
  } finally {
    loading.value = false
  }
}
onMounted(load)
watch(kind, (value) => {
  router.replace({ query: value === 'all' ? {} : { kind: value } })
  load()
})
let debounce: ReturnType<typeof setTimeout> | null = null
watch(q, () => {
  if (debounce) clearTimeout(debounce)
  debounce = setTimeout(load, 250)
})

const columns: TableColumnsType = [
  { title: 'Tenant', key: 'name' },
  { title: 'Type', key: 'kind', width: 130 },
  { title: 'Monitoring', key: 'assets', responsive: ['md'] },
  { title: 'Keys', dataIndex: 'active_keys', width: 70, responsive: ['lg'] },
  { title: 'Last data', key: 'seen', responsive: ['md'] },
  { title: 'Demo ends', key: 'expires', responsive: ['lg'] },
  { title: 'Created', key: 'created', responsive: ['xl'] },
]

// --- new customer ---
const drawer = ref(false)
const form = ref({ name: '', slug: '' })
const creating = ref(false)
const createError = ref<string | null>(null)
const issued = ref<{ id: string; key: IssuedKey } | null>(null)

async function submit() {
  creating.value = true
  createError.value = null
  try {
    const result = await createTenant({
      name: form.value.name.trim(),
      slug: form.value.slug.trim() || undefined,
    })
    issued.value = { id: result.tenant.id, key: result.key }
    load()
  } catch (caught) {
    createError.value = caught instanceof ApiError ? caught.detail : 'Could not create the tenant.'
  } finally {
    creating.value = false
  }
}
function closeDrawer() {
  drawer.value = false
  issued.value = null
  form.value = { name: '', slug: '' }
}
const total = computed(() => rows.value.length)
</script>

<template>
  <div class="page">
    <PageHeader title="Tenants" :subtitle="loading ? undefined : `${total} shown`">
      <template #actions>
        <Button type="primary" @click="drawer = true">New customer</Button>
      </template>
    </PageHeader>

    <div class="filters">
      <SegmentedControl v-model="kind" :options="KINDS" aria-label="Tenant type" />
      <Input v-model:value="q" placeholder="Search name or slug" allow-clear class="search" />
    </div>

    <Alert v-if="error" type="error" :message="error" show-icon class="mb" />

    <Table
      :columns="columns"
      :data-source="rows"
      :loading="loading"
      row-key="id"
      size="middle"
      :pagination="{ pageSize: 25, hideOnSinglePage: true }"
      :custom-row="(row: TenantRow) => ({ onClick: () => router.push({ name: 'admin-tenant', params: { id: row.id } }), class: 'clickable' })"
    >
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'name'">
          <RouterLink :to="{ name: 'admin-tenant', params: { id: record.id } }" class="name" @click.stop>
            {{ record.name }}
          </RouterLink>
          <div class="slug">{{ record.slug }}<template v-if="record.coupon_code"> · {{ record.coupon_code }}</template></div>
        </template>
        <template v-else-if="column.key === 'kind'">
          <StatusChip :state="KIND_STATE[record.kind as TenantKind]" :label="KIND_LABEL[record.kind as TenantKind]" size="sm" />
        </template>
        <template v-else-if="column.key === 'assets'">
          {{ record.sites }} site{{ record.sites === 1 ? '' : 's' }} · {{ record.generators }} gen ·
          {{ record.tractors }} tractor{{ record.tractors === 1 ? '' : 's' }}
        </template>
        <template v-else-if="column.key === 'seen'">
          {{ record.last_reading_at ? relativeTime(record.last_reading_at) : 'none in 2 days' }}
        </template>
        <template v-else-if="column.key === 'expires'">
          {{ record.kind === 'real' ? '—' : untilText(record.demo_expires_at) }}
        </template>
        <template v-else-if="column.key === 'created'">{{ date(record.created_at) }}</template>
      </template>
    </Table>

    <Drawer :open="drawer" title="New customer" :width="420" @close="closeDrawer">
      <template v-if="!issued">
        <form class="form" @submit.prevent="submit">
          <p class="note">
            Creates a paying tenant (not a demo) and its first API key. To turn an existing demo
            into a customer, use <strong>Convert</strong> on that demo instead — its data is kept.
          </p>
          <label class="field">
            <span>Company name</span>
            <Input v-model:value="form.name" placeholder="e.g. Access Bank — Lagos cluster" />
          </label>
          <label class="field">
            <span>Slug <span class="opt">optional, derived from the name</span></span>
            <Input v-model:value="form.slug" placeholder="access-bank-lagos" />
          </label>
          <Alert v-if="createError" type="error" :message="createError" show-icon />
          <Button type="primary" html-type="submit" :loading="creating" :disabled="form.name.trim().length < 2">
            Create tenant
          </Button>
        </form>
      </template>
      <template v-else>
        <div class="form">
          <p class="note">Tenant created. Send this key to the customer through a secure channel.</p>
          <KeyReveal :api-key="issued.key.api_key" />
          <Button @click="router.push({ name: 'admin-tenant', params: { id: issued.id } })">Open tenant</Button>
        </div>
      </template>
    </Drawer>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 28px 28px 72px } }
.filters { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 14px; align-items: center }
.search { max-width: 280px }
.mb { margin-bottom: 14px }
.name { font-weight: 600 }
.slug { font-size: 12px; color: var(--ink-muted) }
:deep(.clickable) { cursor: pointer }
.form { display: flex; flex-direction: column; gap: 14px }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 600 }
.opt { font-weight: 400; color: var(--ink-muted) }
.note { margin: 0; font-size: 13px; color: var(--ink-muted) }
</style>
