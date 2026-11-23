<script setup lang="ts">
/** One coupon: its terms, who redeemed it, and switches to change it. */
import { computed, onMounted, ref } from 'vue'
import { Alert, App as AntApp, Button, InputNumber, Switch, Table } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import AppCard from '@/components/ui/AppCard.vue'
import PageHeader from '@/components/ui/PageHeader.vue'
import SectionHeading from '@/components/ui/SectionHeading.vue'
import SkeletonBlock from '@/components/ui/SkeletonBlock.vue'
import DataList from '@/components/ui/DataList.vue'
import DataListItem from '@/components/ui/DataListItem.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { getCoupon, updateCoupon } from '@/api/admin'
import type { CouponDetail } from '@/api/adminTypes'
import { ApiError } from '@/api/client'
import { date, dateTime } from '@/lib/adminFormat'

const props = defineProps<{ id: string }>()
const { message } = AntApp.useApp()
const coupon = ref<CouponDetail | null>(null)
const error = ref<string | null>(null)
const saving = ref(false)
const uses = ref(1)

async function load() {
  try {
    coupon.value = await getCoupon(props.id)
    uses.value = coupon.value.max_redemptions
    document.title = `${coupon.value.code} · Admin`
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : 'Could not load the coupon.'
  }
}
onMounted(load)

async function save(body: Parameters<typeof updateCoupon>[1], done: string) {
  if (!coupon.value) return
  saving.value = true
  try {
    await updateCoupon(coupon.value.id, body)
    message.success(done)
    await load()
  } catch (caught) {
    message.error(caught instanceof ApiError ? caught.detail : 'Could not save.')
  } finally {
    saving.value = false
  }
}

const link = computed(() =>
  coupon.value ? `${window.location.origin}/demo?code=${encodeURIComponent(coupon.value.code)}` : '',
)
async function copy() {
  try {
    await navigator.clipboard.writeText(link.value)
    message.success('Signup link copied.')
  } catch {
    message.info(link.value)
  }
}

const columns: TableColumnsType = [
  { title: 'Company', key: 'company' },
  { title: 'Contact', dataIndex: 'contact_email', responsive: ['md'] },
  { title: 'Redeemed', key: 'at' },
]
</script>

<template>
  <div class="page">
    <SkeletonBlock v-if="!coupon && !error" height="300px" />
    <Alert v-else-if="error" type="error" :message="error" show-icon />
    <template v-else-if="coupon">
      <PageHeader :title="coupon.code" :subtitle="coupon.label ?? undefined" back-to="/admin/coupons" back-label="Coupons" />

      <div class="layout">
        <div class="stack">
          <AppCard>
            <DataList>
              <DataListItem label="Used">{{ coupon.redemptions_count }} of {{ coupon.max_redemptions }}</DataListItem>
              <DataListItem label="Code expires">{{ coupon.expires_at ? date(coupon.expires_at) : 'never' }}</DataListItem>
              <DataListItem label="Demo length">{{ coupon.demo_duration_days }} days</DataListItem>
              <DataListItem label="Limits">
                {{ coupon.max_locations }} location(s) · {{ coupon.max_tractors }} tractor(s) ·
                {{ coupon.max_generators_per_location }} generators per location
              </DataListItem>
              <DataListItem label="Created">{{ date(coupon.created_at) }}</DataListItem>
            </DataList>
          </AppCard>

          <AppCard>
            <SectionHeading title="Controls" :level="3" />
            <div class="control">
              <div>
                <div class="strong">Accepting signups</div>
                <div class="muted">Off stops new redemptions. Demos already open are unaffected.</div>
              </div>
              <Switch
                :checked="coupon.is_active"
                :loading="saving"
                aria-label="Accepting signups"
                @change="(on: unknown) => save({ is_active: Boolean(on) }, on ? 'Coupon switched on.' : 'Coupon switched off.')"
              />
            </div>
            <div class="control">
              <div>
                <div class="strong">Uses</div>
                <div class="muted">Cannot go below the {{ coupon.redemptions_count }} already made.</div>
              </div>
              <div class="inline">
                <InputNumber v-model:value="uses" :min="Math.max(1, coupon.redemptions_count)" :max="10000" style="width: 100px" />
                <Button :disabled="uses === coupon.max_redemptions" :loading="saving" @click="save({ max_redemptions: uses }, 'Uses updated.')">
                  Save
                </Button>
              </div>
            </div>
            <div class="control">
              <div>
                <div class="strong">Signup link</div>
                <div class="muted mono">{{ link }}</div>
              </div>
              <Button @click="copy">Copy</Button>
            </div>
          </AppCard>
        </div>

        <AppCard>
          <SectionHeading title="Redemptions" :level="3" :hint="`${coupon.redemptions.length}`" />
          <Table
            v-if="coupon.redemptions.length"
            :columns="columns"
            :data-source="coupon.redemptions"
            row-key="id"
            size="small"
            :pagination="{ pageSize: 20, hideOnSinglePage: true }"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'company'">
                <RouterLink v-if="record.organisation_id" :to="{ name: 'admin-tenant', params: { id: record.organisation_id } }">
                  {{ record.company_name }}
                </RouterLink>
                <span v-else>{{ record.company_name }} <span class="muted">(purged)</span></span>
              </template>
              <template v-else-if="column.key === 'at'">{{ dateTime(record.redeemed_at) }}</template>
            </template>
          </Table>
          <EmptyState v-else title="Nobody has used this code yet." />
        </AppCard>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 28px 28px 72px } }
.layout { display: grid; gap: 14px; grid-template-columns: 1fr }
@media (min-width: 1100px) { .layout { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) } }
.stack { display: flex; flex-direction: column; gap: 14px; min-width: 0 }
.control { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px 0 }
.control + .control { border-top: 1px solid var(--hairline) }
.strong { font-weight: 600; font-size: 14px }
.muted { font-size: 12px; color: var(--ink-muted) }
.mono { font-family: 'IBM Plex Mono', monospace; word-break: break-all }
.inline { display: flex; gap: 8px; flex: none }
</style>
