<script setup lang="ts">
/** Who did what on the platform, newest first. */
import { onMounted, ref, watch } from 'vue'
import { Alert, Button } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SegmentedControl from '@/components/ui/SegmentedControl.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { listAudit } from '@/api/admin'
import type { AuditEntry } from '@/api/adminTypes'
import { dateTime } from '@/lib/adminFormat'

const FILTERS = [
  { label: 'All', value: '' },
  { label: 'Tenants', value: 'tenant.' },
  { label: 'Keys', value: 'key.' },
  { label: 'Coupons', value: 'coupon.' },
  { label: 'Admins', value: 'admin.' },
  { label: 'System', value: 'system.' },
]
const filter = ref('')
const items = ref<AuditEntry[]>([])
const cursor = ref<string | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

async function load(more = false) {
  loading.value = true
  try {
    const page = await listAudit({
      action: filter.value || undefined,
      before: more ? (cursor.value ?? undefined) : undefined,
      limit: 100,
    })
    items.value = more ? [...items.value, ...page.items] : page.items
    cursor.value = page.next_cursor
    error.value = null
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load the audit log.'
  } finally {
    loading.value = false
  }
}
onMounted(() => load())
watch(filter, () => load())

const LABELS: Record<string, string> = {
  'admin.login': 'signed in',
  'admin.create': 'added an admin',
  'admin.update': 'changed an admin',
  'tenant.create': 'created a customer',
  'tenant.extend': 'extended a demo',
  'tenant.convert': 'converted a demo',
  'tenant.purge': 'purged a tenant',
  'key.issue': 'issued an API key',
  'key.revoke': 'revoked an API key',
  'coupon.create': 'created a coupon',
  'coupon.update': 'changed a coupon',
  'backfill.retry': 'retried a backfill',
  'system.tick': 'ran a tick',
  'system.expire': 'ran demo expiry',
  'tuning.update': 'changed incident tuning',
}

/** The detail fields worth a glance, as "key: value" pairs. */
function summary(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .filter(([key]) => !['before', 'after', 'changes'].includes(key))
    .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value) : String(value)}`)
    .join(' · ')
}
</script>

<template>
  <div class="page">
    <PageHeader title="Audit log" subtitle="Every change made from the console or with the break-glass key" />
    <SegmentedControl v-model="filter" :options="FILTERS" aria-label="Filter by area" class="mb" />
    <Alert v-if="error" type="error" :message="error" show-icon class="mb" />

    <AppCard>
      <ol v-if="items.length" class="log">
        <li v-for="e in items" :key="e.id">
          <time class="when">{{ dateTime(e.at) }}</time>
          <div class="what">
            <span class="actor">{{ e.actor_label }}</span>
            {{ LABELS[e.action] ?? e.action }}
            <RouterLink
              v-if="e.target_type === 'tenant' && e.target_id && e.action !== 'tenant.purge'"
              :to="{ name: 'admin-tenant', params: { id: e.target_id } }"
              class="target"
              >open</RouterLink
            >
            <div v-if="summary(e.detail)" class="detail">{{ summary(e.detail) }}</div>
          </div>
        </li>
      </ol>
      <EmptyState v-else-if="!loading" title="Nothing recorded yet." />
      <div v-if="cursor" class="more">
        <Button :loading="loading" @click="load(true)">Load older</Button>
      </div>
    </AppCard>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 28px 28px 72px } }
.mb { margin-bottom: 14px; display: inline-flex }
.log { list-style: none; margin: 0; padding: 0 }
.log li { display: grid; grid-template-columns: 1fr; gap: 2px; padding: 10px 0 }
@media (min-width: 640px) { .log li { grid-template-columns: 150px minmax(0, 1fr); gap: 14px } }
.log li + li { border-top: 1px solid var(--hairline) }
.when { font-size: 12px; color: var(--ink-muted); font-variant-numeric: tabular-nums }
.what { font-size: 14px; min-width: 0 }
.actor { font-weight: 600 }
.target { margin-left: 6px; font-size: 12px }
.detail { font-size: 12px; color: var(--ink-muted); overflow-wrap: anywhere }
.more { display: flex; justify-content: center; padding-top: 12px }
</style>
