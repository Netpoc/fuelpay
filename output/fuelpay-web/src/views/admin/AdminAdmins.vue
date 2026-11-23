<script setup lang="ts">
/** Who can operate the platform (owners only). */
import { onMounted, ref } from 'vue'
import { Alert, App as AntApp, Button, Drawer, Input, InputPassword, Modal, Select, Switch, Table } from 'ant-design-vue'
import type { TableColumnsType } from 'ant-design-vue'

import PageHeader from '@/components/ui/PageHeader.vue'
import { createAdmin, listAdmins, updateAdmin } from '@/api/admin'
import type { Admin, AdminRole } from '@/api/adminTypes'
import { ApiError } from '@/api/client'
import { dateTime } from '@/lib/adminFormat'
import { useAdminAuthStore } from '@/stores/adminAuth'

const auth = useAdminAuthStore()
const { message } = AntApp.useApp()
const rows = ref<Admin[]>([])
const loading = ref(true)
const ROLES = [
  { value: 'OWNER', label: 'Owner' },
  { value: 'STAFF', label: 'Staff' },
]

async function load() {
  loading.value = true
  try {
    rows.value = await listAdmins()
  } finally {
    loading.value = false
  }
}
onMounted(load)

async function patch(admin: Admin, body: Parameters<typeof updateAdmin>[1], done: string) {
  try {
    await updateAdmin(admin.id!, body)
    message.success(done)
  } catch (caught) {
    message.error(caught instanceof ApiError ? caught.detail : 'Could not save.')
  }
  load()
}

const columns: TableColumnsType = [
  { title: 'Admin', key: 'who' },
  { title: 'Role', key: 'role', width: 140 },
  { title: 'Active', key: 'active', width: 90 },
  { title: 'Last sign-in', key: 'login', responsive: ['md'] },
  { title: '', key: 'actions', width: 150 },
]

// --- add ---
const drawer = ref(false)
const form = ref({ email: '', name: '', password: '', role: 'STAFF' as AdminRole })
const saving = ref(false)
const saveError = ref<string | null>(null)
async function submit() {
  saving.value = true
  saveError.value = null
  try {
    await createAdmin(form.value)
    message.success(`${form.value.email} added.`)
    drawer.value = false
    form.value = { email: '', name: '', password: '', role: 'STAFF' }
    load()
  } catch (caught) {
    saveError.value = caught instanceof ApiError ? caught.detail : 'Could not add the admin.'
  } finally {
    saving.value = false
  }
}

// --- reset password ---
const resetFor = ref<Admin | null>(null)
const newPassword = ref('')
async function resetPassword() {
  if (!resetFor.value) return
  await patch(resetFor.value, { password: newPassword.value }, 'Password reset. Their sessions were signed out.')
  resetFor.value = null
  newPassword.value = ''
}
const isSelf = (row: Admin) => row.id === auth.profile?.admin.id
</script>

<template>
  <div class="page">
    <PageHeader title="Admins" subtitle="People who can operate the platform">
      <template #actions>
        <Button type="primary" @click="drawer = true">Add admin</Button>
      </template>
    </PageHeader>

    <Table :columns="columns" :data-source="rows" :loading="loading" row-key="id" size="middle" :pagination="false">
      <template #bodyCell="{ column, record }">
        <template v-if="column.key === 'who'">
          <div class="strong">{{ record.name }} <span v-if="isSelf(record as Admin)" class="you">you</span></div>
          <div class="muted">{{ record.email }}</div>
        </template>
        <template v-else-if="column.key === 'role'">
          <Select
            :value="record.role"
            :options="ROLES"
            size="small"
            style="width: 110px"
            :aria-label="`Role for ${record.email}`"
            @change="(v: unknown) => patch(record as Admin, { role: v as AdminRole }, 'Role changed.')"
          />
        </template>
        <template v-else-if="column.key === 'active'">
          <Switch
            :checked="record.is_active"
            :disabled="isSelf(record as Admin)"
            size="small"
            :aria-label="`${record.email} active`"
            @change="(on: unknown) => patch(record as Admin, { is_active: Boolean(on) }, on ? 'Reactivated.' : 'Deactivated and signed out.')"
          />
        </template>
        <template v-else-if="column.key === 'login'">{{ dateTime(record.last_login_at) }}</template>
        <template v-else-if="column.key === 'actions'">
          <Button size="small" @click="resetFor = record as Admin">Reset password</Button>
        </template>
      </template>
    </Table>

    <Drawer :open="drawer" title="Add admin" :width="400" @close="drawer = false">
      <form class="form" @submit.prevent="submit">
        <label class="field"><span>Name</span><Input v-model:value="form.name" /></label>
        <label class="field"><span>Email</span><Input v-model:value="form.email" type="email" /></label>
        <label class="field">
          <span>Temporary password <span class="opt">10+ characters; share it securely</span></span>
          <InputPassword v-model:value="form.password" autocomplete="new-password" />
        </label>
        <label class="field">
          <span>Role</span>
          <Select v-model:value="form.role" :options="ROLES" />
        </label>
        <p class="note">Owners can also manage admins and change incident tuning for every tenant.</p>
        <Alert v-if="saveError" type="error" :message="saveError" show-icon />
        <Button type="primary" html-type="submit" :loading="saving">Add admin</Button>
      </form>
    </Drawer>

    <Modal
      :open="!!resetFor"
      :title="`Reset password for ${resetFor?.email}`"
      ok-text="Reset"
      :ok-button-props="{ disabled: newPassword.length < 10 }"
      @ok="resetPassword"
      @cancel="resetFor = null; newPassword = ''"
    >
      <p class="note">They will be signed out everywhere and need the new password to sign in.</p>
      <InputPassword v-model:value="newPassword" autocomplete="new-password" aria-label="New password" />
    </Modal>
  </div>
</template>

<style scoped>
.page { max-width: 82rem; margin: 0 auto; padding: 20px 16px 56px }
@media (min-width: 768px) { .page { padding: 28px 28px 72px } }
.strong { font-weight: 600 }
.muted { font-size: 12px; color: var(--ink-muted) }
.you {
  margin-left: 4px; padding: 0 6px; border-radius: 999px; font-size: 10px; font-weight: 700;
  background: var(--surface-sunken); color: var(--ink-muted);
}
.form { display: flex; flex-direction: column; gap: 14px }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 600 }
.opt { font-weight: 400; color: var(--ink-muted) }
.note { margin: 0 0 8px; font-size: 13px; color: var(--ink-muted) }
</style>
