<script setup lang="ts">
/** Email and password sign-in for platform admins. */
import { ref } from 'vue'
import { Alert, Button, Input, InputPassword } from 'ant-design-vue'

import AppLogo from '@/components/ui/AppLogo.vue'
import { useAdminAuthStore } from '@/stores/adminAuth'

const admin = useAdminAuthStore()
const email = ref('')
const password = ref('')
const busy = ref(false)

async function submit() {
  if (!email.value || !password.value) return
  busy.value = true
  await admin.signIn(email.value, password.value)
  busy.value = false
  password.value = ''
}
</script>

<template>
  <div class="wrap">
    <form class="card" @submit.prevent="submit">
      <div class="brand">
        <AppLogo :size="26" />
        <span class="badge">Admin</span>
      </div>
      <h1>Platform console</h1>
      <p class="sub">For FuelPay staff. Customers sign in at the main app.</p>

      <Alert v-if="admin.error" type="error" :message="admin.error" show-icon role="alert" />

      <label class="field">
        <span>Email</span>
        <Input v-model:value="email" size="large" autocomplete="username" type="email" />
      </label>
      <label class="field">
        <span>Password</span>
        <InputPassword v-model:value="password" size="large" autocomplete="current-password" />
      </label>
      <Button type="primary" size="large" html-type="submit" block :loading="busy" :disabled="!email || !password">
        Sign in
      </Button>
      <p class="hint">
        No account yet? An owner adds you, or run
        <code>python -m app.cli create-admin</code> on the server.
      </p>
    </form>
  </div>
</template>

<style scoped>
.wrap { min-height: 100vh; display: grid; place-items: center; padding: 24px 16px; background: var(--surface) }
.card {
  width: 100%; max-width: 24rem; display: flex; flex-direction: column; gap: 14px;
  padding: 28px 24px; background: var(--surface-raised);
  border: 1px solid var(--hairline); border-radius: var(--radius-panel);
}
.brand { display: flex; align-items: center; gap: 10px; color: var(--ink) }
.badge {
  padding: 1px 8px; border-radius: 999px; background: #0b2545; color: #f2a93b;
  font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase;
}
h1 { margin: 6px 0 0; font-size: 22px; font-weight: 600 }
.sub { margin: -8px 0 4px; font-size: 13px; color: var(--ink-muted) }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 600 }
.hint { margin: 4px 0 0; font-size: 12px; color: var(--ink-muted) }
code { font-size: 11px }
</style>
