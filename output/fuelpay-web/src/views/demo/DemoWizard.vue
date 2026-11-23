<script setup lang="ts">
/**
 * Coupon signup: code → company → key → location or tractor → generating.
 *
 * Public, outside the app shell: it has to work before a key exists. A demo
 * user who is already signed in lands straight on "what do you want to add",
 * which is also where the banner's "Add" buttons point.
 *
 * The key is shown once, on its own step, with a copy button. It is already
 * saved in this browser by then — the step is there so the prospect can keep
 * it for another device, not because they have to paste it anywhere.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { Alert, Button, Input, Progress } from 'ant-design-vue'

import AppLogo from '@/components/ui/AppLogo.vue'
import ThemeToggle from '@/components/ui/ThemeToggle.vue'
import LocationForm from '@/components/demo/LocationForm.vue'
import TractorForm from '@/components/demo/TractorForm.vue'
import { ApiError } from '@/api/client'
import { createLocation, createTractor, redeemCoupon } from '@/api/demo'
import type { LocationInput, Provisioned, RedeemResult, TractorInput } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { useDemoStore } from '@/stores/demo'

type Step = 'code' | 'key' | 'choose' | 'location' | 'tractor' | 'generating' | 'not-demo'

const auth = useAuthStore()
const demo = useDemoStore()
const route = useRoute()
const router = useRouter()

const step = ref<Step>('code')
const busy = ref(false)
const error = ref<string | null>(null)

const code = ref(typeof route.query.code === 'string' ? route.query.code : '')
const company = ref('')
const email = ref('')
const issued = ref<RedeemResult | null>(null)
const copied = ref(false)
const created = ref<Provisioned[]>([])

let stopPolling: (() => void) | null = null
function startPolling() {
  if (!stopPolling) stopPolling = demo.watch()
}
onBeforeUnmount(() => stopPolling?.())

onMounted(async () => {
  if (auth.status === 'unknown' || auth.status === 'checking') await auth.verify()
  if (!auth.isAuthenticated) return
  const status = await demo.load()
  if (!status?.is_demo) {
    step.value = 'not-demo'
    return
  }
  startPolling()
  const wanted = route.query.add
  step.value =
    wanted === 'tractor' && demo.canAddTractor
      ? 'tractor'
      : wanted === 'location' && demo.canAddLocation
        ? 'location'
        : 'choose'
})

const STEPS: { key: Step; label: string }[] = [
  { key: 'code', label: 'Code' },
  { key: 'key', label: 'Access key' },
  { key: 'choose', label: 'What to monitor' },
  { key: 'location', label: 'Details' },
  { key: 'generating', label: 'Live data' },
]
const stepIndex = computed(() => {
  const key = step.value === 'tractor' ? 'location' : step.value
  return STEPS.findIndex((s) => s.key === key)
})

function explain(caught: unknown, fallback: string) {
  if (caught instanceof ApiError) {
    if (caught.status === 429) return 'Too many attempts. Wait a minute and try again.'
    return caught.detail
  }
  return caught instanceof Error ? caught.message : fallback
}

async function redeem() {
  if (!code.value.trim() || company.value.trim().length < 2) return
  busy.value = true
  error.value = null
  try {
    issued.value = await redeemCoupon({
      code: code.value.trim(),
      company_name: company.value.trim(),
      contact_email: email.value.trim() || undefined,
    })
    await auth.setKey(issued.value.api_key)
    await demo.load()
    startPolling()
    step.value = 'key'
  } catch (caught) {
    error.value = explain(caught, 'Could not redeem that code.')
  } finally {
    busy.value = false
  }
}

async function copyKey() {
  if (!issued.value) return
  try {
    await navigator.clipboard.writeText(issued.value.api_key)
    copied.value = true
  } catch {
    // Clipboard can be refused (insecure origin, permissions); the key is
    // selectable in the field regardless.
  }
}

async function provision(run: () => Promise<Provisioned>) {
  busy.value = true
  error.value = null
  try {
    created.value.push(await run())
    await demo.load()
    step.value = 'generating'
  } catch (caught) {
    error.value = explain(caught, 'Could not create it.')
  } finally {
    busy.value = false
  }
}
const submitLocation = (body: LocationInput) => provision(() => createLocation(body))
const submitTractor = (body: TractorInput) => provision(() => createTractor(body))

const progressRows = computed(() =>
  created.value.map((item) => {
    const live = demo.entity(item.id)
    return {
      ...item,
      status: live?.simulation_status ?? item.simulation_status,
      progress: Math.round((live?.progress ?? 0) * 100),
      error: live?.error ?? null,
    }
  }),
)
const allLive = computed(
  () => progressRows.value.length > 0 && progressRows.value.every((r) => r.status === 'LIVE'),
)

function open(row: { type: string; id: string }) {
  router.push(
    row.type === 'tractor' ? { name: 'vehicle', params: { id: row.id } } : { name: 'site', params: { id: row.id } },
  )
}

watch(step, () => {
  error.value = null
  window.scrollTo({ top: 0 })
})
</script>

<template>
  <div class="wizard">
    <header class="top">
      <RouterLink :to="auth.isAuthenticated ? '/fleet' : '/'" aria-label="FuelPay home">
        <AppLogo :size="26" />
      </RouterLink>
      <ThemeToggle />
    </header>

    <main class="body">
      <ol v-if="step !== 'not-demo'" class="steps" aria-label="Progress">
        <li
          v-for="(s, i) in STEPS"
          :key="s.key"
          :class="{ done: i < stepIndex, current: i === stepIndex }"
          :aria-current="i === stepIndex ? 'step' : undefined"
        >
          <span class="num">{{ i < stepIndex ? '✓' : i + 1 }}</span>
          <span class="txt">{{ s.label }}</span>
        </li>
      </ol>

      <section class="card">
        <!-- 1. Code -->
        <template v-if="step === 'code'">
          <h1>Start your FuelPay demo</h1>
          <p class="sub">
            Enter the PoC code you were given. You'll set up a real location or tractor, and
            FuelPay will stream simulated sensor data for it — with a month of history ready on
            arrival.
          </p>
          <form class="stack" @submit.prevent="redeem">
            <label class="field">
              <span class="label">PoC code</span>
              <Input v-model:value="code" placeholder="XXXX-XXXX" size="large" autocomplete="off" class="mono" />
            </label>
            <label class="field">
              <span class="label">Company name</span>
              <Input v-model:value="company" placeholder="e.g. Ada Farms Ltd" size="large" autocomplete="organization" />
            </label>
            <label class="field">
              <span class="label">Work email <span class="opt">optional</span></span>
              <Input v-model:value="email" type="email" size="large" autocomplete="email" />
            </label>
            <Alert v-if="error" type="error" :message="error" show-icon role="alert" />
            <Button
              type="primary"
              size="large"
              html-type="submit"
              block
              :loading="busy"
              :disabled="!code.trim() || company.trim().length < 2"
              >Create demo account</Button
            >
          </form>
          <p class="aside">Already have a key? <RouterLink to="/fleet">Sign in</RouterLink></p>
        </template>

        <!-- 2. Key -->
        <template v-else-if="step === 'key' && issued">
          <h1>{{ issued.organisation.name }} is ready</h1>
          <p class="sub">
            This is your access key. It's saved in this browser already — keep a copy if you
            want to open the demo somewhere else. <strong>It won't be shown again.</strong>
          </p>
          <div class="keyrow">
            <Input :value="issued.api_key" readonly size="large" class="mono" aria-label="Your API key" />
            <Button size="large" @click="copyKey">{{ copied ? 'Copied' : 'Copy' }}</Button>
          </div>
          <ul class="facts">
            <li>
              Demo ends <strong>{{ new Date(issued.expires_at).toLocaleDateString(undefined, { day: 'numeric', month: 'long' }) }}</strong>
            </li>
            <li>Up to {{ issued.limits.max_locations }} location(s) and {{ issued.limits.max_tractors }} tractor(s)</li>
          </ul>
          <Button type="primary" size="large" block @click="step = 'choose'">Continue</Button>
        </template>

        <!-- 3. Choose -->
        <template v-else-if="step === 'choose'">
          <h1>What would you like to monitor?</h1>
          <p class="sub">You can add more later from the demo banner, up to your limits.</p>
          <div class="choices">
            <button
              type="button"
              class="choice"
              :disabled="!demo.canAddLocation"
              @click="step = 'location'"
            >
              <svg viewBox="0 0 48 48" class="choice__icon" aria-hidden="true">
                <rect x="10" y="10" width="28" height="30" rx="4" fill="none" stroke="currentColor" stroke-width="2.2" />
                <rect x="10" y="24" width="28" height="16" rx="0" fill="var(--accent)" opacity=".55" />
                <path d="M18 6h12" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" />
              </svg>
              <span class="choice__title">Diesel tank site</span>
              <span class="choice__sub">Generators with day tanks, plus bulk storage — a bank branch, tower or office.</span>
              <span class="choice__limit">
                {{ demo.status?.usage.locations ?? 0 }} of {{ demo.status?.limits?.max_locations ?? 0 }} used
              </span>
            </button>
            <button
              type="button"
              class="choice"
              :disabled="!demo.canAddTractor"
              @click="step = 'tractor'"
            >
              <svg viewBox="0 0 48 48" class="choice__icon" aria-hidden="true">
                <circle cx="14" cy="34" r="7" fill="none" stroke="currentColor" stroke-width="2.2" />
                <circle cx="36" cy="36" r="5" fill="none" stroke="currentColor" stroke-width="2.2" />
                <path d="M8 28V18h14l4 10h14v6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round" />
                <rect x="28" y="12" width="6" height="16" fill="var(--accent)" opacity=".55" />
              </svg>
              <span class="choice__title">Tractor</span>
              <span class="choice__sub">Fuel level, engine data and GPS track as it works a field — with theft and misuse alerts.</span>
              <span class="choice__limit">
                {{ demo.status?.usage.tractors ?? 0 }} of {{ demo.status?.limits?.max_tractors ?? 0 }} used
              </span>
            </button>
          </div>
          <p v-if="!demo.canAddLocation && !demo.canAddTractor" class="aside">
            You've used every slot on this demo. <RouterLink to="/fleet">Go to the dashboard</RouterLink>
          </p>
        </template>

        <!-- 4. Details -->
        <template v-else-if="step === 'location'">
          <h1>Your location</h1>
          <p class="sub">Describe the site as it really is. Sensor data starts from what you enter here.</p>
          <LocationForm
            :max-generators="demo.status?.limits?.max_generators_per_location ?? 3"
            :submitting="busy"
            :error="error"
            @submit="submitLocation"
            @cancel="step = 'choose'"
          />
        </template>

        <template v-else-if="step === 'tractor'">
          <h1>Your tractor</h1>
          <p class="sub">Place its yard and the field it works. Both are used for the GPS track.</p>
          <TractorForm :submitting="busy" :error="error" @submit="submitTractor" @cancel="step = 'choose'" />
        </template>

        <!-- 5. Generating -->
        <template v-else-if="step === 'generating'">
          <h1>{{ allLive ? 'Your data is live' : 'Generating your data…' }}</h1>
          <p class="sub">
            {{
              allLive
                ? 'A month of history is in place, and new readings arrive every few minutes from now on.'
                : 'Building 30 days of realistic history: consumption, refuels and the occasional incident. This takes a few seconds.'
            }}
          </p>
          <ul class="progress">
            <li v-for="row in progressRows" :key="row.id">
              <div class="progress__head">
                <span class="progress__name">{{ row.name }}</span>
                <span class="progress__type">{{ row.type === 'tractor' ? 'Tractor' : 'Location' }}</span>
              </div>
              <Progress
                :percent="row.status === 'LIVE' ? 100 : row.progress"
                :status="row.status === 'FAILED' ? 'exception' : row.status === 'LIVE' ? 'success' : 'active'"
                :show-info="true"
              />
              <p v-if="row.error" class="err">{{ row.error }}</p>
              <Button v-if="row.status === 'LIVE'" type="primary" @click="open(row)">
                Open {{ row.type === 'tractor' ? 'tractor' : 'location' }} →
              </Button>
            </li>
          </ul>
          <div class="actions">
            <Button v-if="demo.canAddLocation || demo.canAddTractor" @click="step = 'choose'">Add another</Button>
            <Button :type="allLive ? 'default' : 'link'" @click="router.push('/fleet')">Go to dashboard</Button>
          </div>
        </template>

        <!-- Signed in, but not a demo tenant -->
        <template v-else-if="step === 'not-demo'">
          <h1>You're signed in to a full account</h1>
          <p class="sub">PoC codes open separate demo accounts. Sign out first to start one.</p>
          <div class="actions">
            <Button @click="router.push('/fleet')">Back to the dashboard</Button>
            <Button type="primary" @click="auth.clear(); demo.reset(); step = 'code'">Sign out and start a demo</Button>
          </div>
        </template>
      </section>
    </main>
  </div>
</template>

<style scoped>
.wizard { min-height: 100vh; background: var(--surface) }
.top {
  display: flex; align-items: center; justify-content: space-between;
  max-width: 52rem; margin: 0 auto; padding: 14px 16px;
}
.top a { color: var(--ink) }
.body { max-width: 52rem; margin: 0 auto; padding: 0 16px 56px }

.steps {
  display: flex; gap: 6px; list-style: none; margin: 4px 0 16px; padding: 0;
  overflow-x: auto; scrollbar-width: none;
}
.steps li {
  display: flex; align-items: center; gap: 6px; flex: none;
  font-size: 12px; color: var(--ink-subtle);
}
.steps li + li::before { content: ''; width: 18px; height: 1px; background: var(--hairline-strong) }
.num {
  display: inline-flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; border-radius: 50%;
  border: 1px solid var(--hairline-strong); font-size: 11px; font-weight: 600;
}
.steps .current { color: var(--ink); font-weight: 600 }
.steps .current .num { background: var(--accent); border-color: var(--accent); color: #0b2545 }
.steps .done .num { background: var(--status-ok); border-color: var(--status-ok); color: var(--on-solid) }
.txt { display: none }
@media (min-width: 640px) { .txt { display: inline } }
.steps .current .txt { display: inline }

.card {
  background: var(--surface-raised); border: 1px solid var(--hairline);
  border-radius: var(--radius-panel); padding: 22px 18px;
}
@media (min-width: 768px) { .card { padding: 32px 36px } }
h1 { margin: 0; font-size: 22px; font-weight: 600; letter-spacing: -0.015em }
.sub { margin: 6px 0 22px; font-size: 14px; color: var(--ink-muted); max-width: 60ch }
.stack { display: flex; flex-direction: column; gap: 14px; max-width: 26rem }
.field { display: flex; flex-direction: column; gap: 6px }
.label { font-size: 13px; font-weight: 600 }
.opt { font-weight: 400; color: var(--ink-muted) }
.mono :deep(input), .mono { font-family: var(--font-mono, 'IBM Plex Mono', monospace) }
.aside { margin: 18px 0 0; font-size: 13px; color: var(--ink-muted) }

.keyrow { display: flex; gap: 8px; margin-bottom: 14px }
.facts { margin: 0 0 20px; padding-left: 18px; font-size: 14px; color: var(--ink-muted) }

.choices { display: grid; gap: 12px; grid-template-columns: 1fr }
@media (min-width: 640px) { .choices { grid-template-columns: 1fr 1fr } }
.choice {
  display: flex; flex-direction: column; align-items: flex-start; gap: 6px; text-align: left;
  padding: 18px; min-height: 180px;
  font: inherit; color: var(--ink);
  background: var(--surface); border: 1px solid var(--hairline); border-radius: var(--radius-card);
  cursor: pointer;
  transition: border-color var(--dur-micro) var(--ease-standard), transform var(--dur-micro) var(--ease-standard);
}
.choice:hover:not(:disabled) { border-color: var(--accent); transform: translateY(-1px) }
.choice:disabled { opacity: 0.5; cursor: not-allowed }
.choice__icon { width: 40px; height: 40px; color: var(--ink) }
.choice__title { font-size: 16px; font-weight: 600 }
.choice__sub { font-size: 13px; color: var(--ink-muted) }
.choice__limit { margin-top: auto; font-size: 12px; color: var(--ink-subtle) }

.progress { list-style: none; margin: 0 0 20px; padding: 0; display: flex; flex-direction: column; gap: 16px }
.progress__head { display: flex; justify-content: space-between; gap: 8px; font-size: 14px }
.progress__name { font-weight: 600 }
.progress__type { color: var(--ink-muted); font-size: 12px }
.err { margin: 4px 0 0; font-size: 12px; color: var(--status-critical-text) }
.actions { display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between }
</style>
