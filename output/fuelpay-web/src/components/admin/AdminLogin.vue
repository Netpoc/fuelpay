<script setup lang="ts">
/** Email and password sign-in for platform admins. */
import { ref } from 'vue'
import { Alert, Button, Input, InputPassword } from 'ant-design-vue'

import AppLogo from '@/components/ui/AppLogo.vue'
import BrandBackdrop from '@/components/brand/BrandBackdrop.vue'
import NsibidiGlossary from '@/components/brand/NsibidiGlossary.vue'
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
    <BrandBackdrop :nsibidi="0.05" ankara="band" band-side="bottom" ink="var(--ink)" />
    <form class="card glass-strong" @submit.prevent="submit">
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
      <NsibidiGlossary class="gloss" />
    </form>
  </div>
</template>

<style scoped>
.wrap {
  position: relative; isolation: isolate;
  min-height: 100vh; display: grid; place-items: center; padding: 24px 16px 72px;
  background: var(--surface);
}
.wrap > :deep(.backdrop) { z-index: -1 }
:root[data-theme='light'] .wrap > :deep(.backdrop .aurora) { opacity: 0.45 }
.card {
  width: 100%; max-width: 25rem; display: flex; flex-direction: column; gap: 14px;
  padding: 30px 26px;
  border-radius: var(--radius-panel);
  box-shadow: var(--elev-2), var(--glass-inset);
}
.brand { display: flex; align-items: center; gap: 10px; color: var(--ink) }
.badge {
  padding: 2px 9px; border-radius: 999px; background: var(--np-night-3); color: var(--np-saffron);
  font-family: var(--font-mono); font-size: 10px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
}
h1 { margin: 6px 0 0; font-size: 28px; font-weight: 800; letter-spacing: -0.03em }
.sub { margin: -8px 0 4px; font-size: 13px; color: var(--ink-muted) }
.field { display: flex; flex-direction: column; gap: 6px; font-size: 13px; font-weight: 700 }
.hint { margin: 4px 0 0; font-size: 12px; color: var(--ink-muted) }
code { font-family: var(--font-mono); font-size: 11px }
.gloss { margin-top: 8px; padding-top: 14px; border-top: 1px solid var(--hairline) }
</style>
