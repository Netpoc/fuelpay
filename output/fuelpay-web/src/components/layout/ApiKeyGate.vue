<script setup lang="ts">
/**
 * Blocks the app until a key resolves to an organisation.
 *
 * An overlay rather than a route: it is one field, and a /login route would
 * add a navigation state to guard on every other route for no gain.
 *
 * The left panel is the product's brand moment, in Netpoc's language: a night
 * field with aurora glow, Nsibidi script and an Ankara band, in both themes.
 * The form sits on frosted glass. Anyone without a key or a PoC code is sent
 * back to Netpoc's FuelPay page to book one.
 */
import { ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Alert, Button, InputPassword } from 'ant-design-vue'

import AppLogo from '@/components/ui/AppLogo.vue'
import BrandBackdrop from '@/components/brand/BrandBackdrop.vue'
import NsibidiGlossary from '@/components/brand/NsibidiGlossary.vue'
import { useAuthStore } from '@/stores/auth'
import { bookPocHref } from '@/lib/netpoc'
import netpocWhite from '@/assets/brand/netpoc-white.png'

const auth = useAuthStore()
const key = ref(auth.apiKey ?? '')
const submitting = ref(false)

// Public "just exploring" key for the seeded demo org. Dev falls back to the
// service's local default; a production build shows the shortcut only when
// VITE_DEMO_API_KEY is set, since anything here ships in the public bundle.
const DEMO_KEY: string =
  import.meta.env.VITE_DEMO_API_KEY ?? (import.meta.env.DEV ? 'dev-local-key-change-me' : '')

const BOOK_POC = bookPocHref('signin')

async function submit() {
  if (!key.value.trim()) return
  submitting.value = true
  await auth.setKey(key.value)
  submitting.value = false
}
</script>

<template>
  <div class="gate">
    <!-- Brand panel: night in both themes -->
    <aside class="brand">
      <BrandBackdrop :nsibidi="0.07" ankara="band" />

      <div class="brand__top reveal">
        <AppLogo variant="horizontal" :size="32" reversed />
        <span class="by">
          by <img :src="netpocWhite" alt="Πέτρος" class="by__logo" />
        </span>
      </div>

      <div class="brand__copy">
        <p class="pill brand__pill reveal" style="--d: 80ms">Diesel · Power · Tractors</p>
        <h2 class="reveal" style="--d: 140ms">
          Know exactly where your <span class="text-ankara">diesel</span> goes.
        </h2>
        <p class="brand__lede reveal" style="--d: 200ms">
          Live tank levels, refill records and theft detection for generator fleets and tractors.
        </p>
      </div>

      <NsibidiGlossary tone="night" class="brand__gloss reveal" style="--d: 320ms" />
    </aside>

    <!-- Form -->
    <main class="form">
      <div class="form__inner glass-strong reveal" style="--d: 120ms">
        <p class="kicker">FuelPay console</p>
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
            class="mt-4"
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

        <div class="paths">
          <RouterLink :to="{ name: 'demo' }" class="path">
            <span class="path__title">Have a PoC code?</span>
            <span class="path__sub">Set up your own site or tractor with simulated live data</span>
            <span class="path__arrow" aria-hidden="true">→</span>
          </RouterLink>
          <a v-if="BOOK_POC" :href="BOOK_POC" class="path path--quiet">
            <span class="path__title">No code yet?</span>
            <span class="path__sub">Book a 60-day PoC with Netpoc</span>
            <span class="path__arrow" aria-hidden="true">↗</span>
          </a>
        </div>
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
@media (min-width: 900px) {
  .gate { grid-template-rows: 1fr; grid-template-columns: 1.1fr 1fr }
}
@media (min-width: 1280px) {
  .gate { grid-template-columns: 1.25fr 1fr }
}

/* ---- Brand panel ------------------------------------------------------- */
.brand {
  position: relative;
  isolation: isolate;
  overflow: hidden;
  background: var(--np-night);
  color: var(--np-ivory);
  /* Clear the Ankara band on the right. */
  padding: 22px calc(clamp(44px, 6vw, 84px) + 20px) 22px 22px;
}
.brand > :not(.backdrop) { position: relative; z-index: 1 }
@media (min-width: 900px) {
  .brand {
    display: flex;
    flex-direction: column;
    padding: 44px calc(clamp(44px, 6vw, 84px) + 44px) 36px 48px;
  }
}
.brand__top { display: flex; align-items: center; flex-wrap: wrap; gap: 10px 16px }
.by {
  display: inline-flex; align-items: center; gap: 7px;
  font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--np-mist);
}
.by__logo { height: 20px; width: auto }

.brand__copy, .brand__gloss { display: none }
@media (min-width: 900px) {
  .brand__copy { display: block; margin-top: auto; padding-top: 56px }
  .brand__gloss { display: block; margin-top: 40px; padding-top: 18px; border-top: 1px solid rgb(245 242 234 / 10%) }
}
.brand__pill {
  margin: 0 0 18px;
  color: var(--np-mist);
  border-color: rgb(245 242 234 / 16%);
  background: rgb(245 242 234 / 5%);
}
.brand__copy h2 {
  margin: 0 0 16px;
  font-size: clamp(36px, 4.2vw, 56px);
  line-height: 1.02;
  letter-spacing: -0.035em;
  font-weight: 800;
  max-width: 13ch;
}
.brand__lede { margin: 0; color: var(--np-mist); max-width: 38ch; font-size: 16px; line-height: 1.55 }

/* ---- Form -------------------------------------------------------------- */
.form {
  position: relative;
  display: flex; align-items: center; justify-content: center;
  padding: 32px 18px 56px;
}
/* A faint saffron glow behind the glass so it reads as glass on both themes. */
.form::before {
  content: ''; position: absolute; inset: 15% 10%; z-index: 0;
  background: radial-gradient(closest-side, color-mix(in srgb, var(--np-saffron) 16%, transparent), transparent);
  filter: blur(40px);
  pointer-events: none;
}
.form__inner {
  position: relative; z-index: 1;
  width: 100%; max-width: 25rem;
  padding: 28px 24px;
  border-radius: var(--radius-panel);
  box-shadow: var(--elev-2), var(--glass-inset);
}
@media (min-width: 480px) { .form__inner { padding: 34px 32px } }
.kicker { margin: 0 0 6px }
h1 { margin: 0; font-size: 32px; font-weight: 800; letter-spacing: -0.03em; line-height: 1.05 }
.sub { margin: 8px 0 22px; font-size: 14px; color: var(--ink-muted) }
.label { display: block; margin-bottom: 6px; font-size: 13px; font-weight: 700 }
.hint { margin: 8px 0 0; font-size: 12px; color: var(--ink-muted) }

.demo {
  display: flex; align-items: center; justify-content: center; gap: 4px;
  margin-top: 16px; font-size: 12px; color: var(--ink-muted);
}

.paths { display: grid; gap: 10px; margin-top: 22px }
.path {
  position: relative;
  display: flex; flex-direction: column; gap: 2px;
  padding: 13px 44px 13px 16px;
  border: 1px solid var(--hairline-strong); border-radius: var(--radius-card);
  background: color-mix(in srgb, var(--interactive) 6%, transparent);
  color: var(--ink); text-decoration: none;
  transition:
    border-color var(--dur-surface) var(--ease-out-expo),
    transform var(--dur-surface) var(--ease-out-expo),
    background var(--dur-surface) var(--ease-out-expo);
}
.path:hover {
  border-color: var(--interactive);
  background: color-mix(in srgb, var(--interactive) 11%, transparent);
  transform: translateY(-2px);
}
.path--quiet { background: transparent }
.path__title { font-size: 14px; font-weight: 700 }
.path__sub { font-size: 12.5px; color: var(--ink-muted) }
.path__arrow {
  position: absolute; right: 16px; top: 50%; translate: 0 -50%;
  font-size: 18px; color: var(--interactive);
  transition: transform var(--dur-surface) var(--ease-out-expo);
}
.path:hover .path__arrow { transform: translateX(3px) }
</style>
