<script setup lang="ts">
/**
 * Blocks the app until a key resolves to an organisation.
 *
 * An overlay rather than a route: it is one field, and a /login route would
 * add a navigation state to guard on every other route for no gain.
 *
 * The left panel is the one place in the product that gets to be a brand
 * moment, so it stays navy in both themes.
 */
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Alert, Button, InputPassword } from 'ant-design-vue'

import AppLogo from '@/components/ui/AppLogo.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const key = ref(auth.apiKey ?? '')
const submitting = ref(false)

// Public "just exploring" key for the seeded demo org. Dev falls back to the
// service's local default; a production build shows the shortcut only when
// VITE_DEMO_API_KEY is set, since anything here ships in the public bundle.
const DEMO_KEY: string =
  import.meta.env.VITE_DEMO_API_KEY ?? (import.meta.env.DEV ? 'dev-local-key-change-me' : '')

async function submit() {
  if (!key.value.trim()) return
  submitting.value = true
  await auth.setKey(key.value)
  submitting.value = false
}
</script>

<template>
  <div class="gate">
    <!-- Brand panel -->
    <aside class="brand">
      <AppLogo variant="horizontal" :size="30" reversed class="brand__logo" />
      <div class="brand__copy">
        <h2>Know exactly where your <span class="amber">diesel</span> goes.</h2>
        <p>Live tank levels, refill records and theft detection for generator fleets.</p>
      </div>
      <!-- A tank bleeding off the corner. Decorative, hence aria-hidden. -->
      <svg class="brand__tank" viewBox="0 0 100 150" aria-hidden="true">
        <ellipse cx="50" cy="26" rx="42" ry="10" fill="none" stroke="#E9EFF6" stroke-width="1.4" />
        <path d="M8 26 L8 124 A42 10 0 0 0 92 124 L92 26" fill="none" stroke="#E9EFF6" stroke-width="1.4" />
        <path d="M8 74 L8 124 A42 10 0 0 0 92 124 L92 74 A42 10 0 0 1 8 74 Z" fill="#F2A93B" opacity=".55" />
      </svg>
    </aside>

    <!-- Form -->
    <main class="form">
      <div class="form__inner">
        <h1>Sign in</h1>
        <p class="sub">Enter the API key for your organisation.</p>

        <Alert
          v-if="auth.error"
          type="error"
          :message="auth.error"
          class="mb-4"
          show-icon
          banner
          role="alert"
        />

        <form @submit.prevent="submit">
          <label class="label" for="fuelpay-key">API key</label>
          <InputPassword
            id="fuelpay-key"
            v-model:value="key"
            placeholder="fp_…"
            size="large"
            autocomplete="off"
            aria-describedby="key-hint"
            :aria-invalid="auth.status === 'invalid' || undefined"
            :status="auth.status === 'invalid' ? 'error' : ''"
          />
          <p id="key-hint" class="hint">
            Stored in this browser only. Keys can be revoked from the API at any time.
          </p>

          <Button
            type="primary"
            size="large"
            html-type="submit"
            block
            class="mt-3"
            :loading="submitting || auth.status === 'checking'"
            :disabled="!key.trim()"
          >
            Connect
          </Button>
        </form>

        <div v-if="DEMO_KEY" class="demo">
          <span>Just exploring?</span>
          <!-- Was a <code> block the user had to select and copy by hand. -->
          <Button size="small" type="link" @click="key = DEMO_KEY">Use the demo key</Button>
        </div>

        <RouterLink :to="{ name: 'demo' }" class="poc">
          <span class="poc__title">Have a PoC code?</span>
          <span class="poc__sub">Set up your own site or tractor with simulated live data →</span>
        </RouterLink>
      </div>
    </main>
  </div>
</template>

<style scoped>
.gate {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: grid;
  grid-template-rows: auto 1fr;
  background: var(--surface);
  overflow-y: auto;
}
@media (min-width: 768px) {
  .gate { grid-template-rows: 1fr; grid-template-columns: 1fr 1fr }
}
@media (min-width: 1280px) {
  .gate { grid-template-columns: 1.1fr 1fr }
}

.brand {
  position: relative;
  overflow: hidden;
  /* Navy in both themes — this is the brand moment, not a themed surface. */
  background: #0b2545;
  color: #e9eff6;
  padding: 22px 24px;
}
@media (min-width: 768px) {
  .brand { display: flex; flex-direction: column; padding: 44px 44px }
}
.brand__logo { color: #e9eff6 }
.brand__copy { display: none }
@media (min-width: 768px) {
  .brand__copy { display: block; margin-top: auto; position: relative; z-index: 1 }
}
.brand__copy h2 {
  margin: 0 0 12px;
  font-size: 34px;
  line-height: 1.12;
  letter-spacing: -0.025em;
  font-weight: 600;
  max-width: 15ch;
}
.brand__copy p { margin: 0; color: #9aabbe; max-width: 34ch; font-size: 15px }
.amber { color: #f2a93b }

.brand__tank {
  position: absolute;
  right: -60px;
  bottom: -70px;
  width: 300px;
  opacity: 0.12;
  display: none;
}
@media (min-width: 768px) { .brand__tank { display: block } }

.form { display: flex; align-items: center; justify-content: center; padding: 32px 20px 56px }
.form__inner { width: 100%; max-width: 22rem }
h1 { margin: 0; font-size: 24px; font-weight: 600; letter-spacing: -0.015em }
.sub { margin: 6px 0 22px; font-size: 14px; color: var(--ink-muted) }
.label { display: block; margin-bottom: 6px; font-size: 13px; font-weight: 600 }
.hint { margin: 8px 0 0; font-size: 12px; color: var(--ink-muted) }
.poc {
  display: flex; flex-direction: column; gap: 2px;
  margin-top: 18px; padding: 12px 14px;
  border: 1px solid var(--hairline); border-radius: var(--radius-card);
  color: var(--ink); text-decoration: none;
  transition: border-color var(--dur-micro) var(--ease-standard);
}
.poc:hover { border-color: var(--accent) }
.poc__title { font-size: 14px; font-weight: 600 }
.poc__sub { font-size: 12px; color: var(--ink-muted) }
.demo {
  display: flex; align-items: center; justify-content: center; gap: 4px;
  margin-top: 22px; font-size: 12px; color: var(--ink-muted);
}
</style>
