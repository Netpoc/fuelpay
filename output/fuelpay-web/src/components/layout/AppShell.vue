<script setup lang="ts">
/**
 * App chrome.
 *
 * Below md the nav collapses into a disclosure. The previous header was a
 * single non-wrapping flex row that survived only because there were exactly
 * two nav items — a third, or a longer org name, overflowed it.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { Button } from 'ant-design-vue'

import AppLogo from '@/components/ui/AppLogo.vue'
import DemoBanner from '@/components/layout/DemoBanner.vue'
import ThemeToggle from '@/components/ui/ThemeToggle.vue'
import LiveIndicator from '@/components/ui/LiveIndicator.vue'
import { useAuthStore } from '@/stores/auth'
import { useDemoStore } from '@/stores/demo'
import { useFleetStore } from '@/stores/fleet'
import { useIncidentsStore } from '@/stores/incidents'
import { useTheme } from '@/composables/useTheme'
import netpocWhite from '@/assets/brand/netpoc-white.png'
import netpocDark from '@/assets/brand/netpoc-dark.png'

const route = useRoute()
const auth = useAuthStore()
const fleet = useFleetStore()
const incidents = useIncidentsStore()
const demo = useDemoStore()
const { resolved } = useTheme()

const open = ref(false)
watch(() => route.fullPath, () => (open.value = false))

// Tractors appear only for tenants that have some; the seeded generator fleet
// has none, and an always-empty tab is noise.
const NAV = computed(() => [
  { name: 'fleet', label: 'Fleet' },
  ...(demo.hasTractors ? [{ name: 'vehicles', label: 'Tractors' }] : []),
  { name: 'incidents', label: 'Incidents' },
])

function signOut() {
  demo.reset()
  auth.clear()
}

/**
 * Every drill-down from the fleet map is still "Fleet" to the nav.
 *
 * Previously only `generator` mapped back, so a tank page — and now a site page
 * — left the nav with nothing marked current at all.
 */
const FLEET_CHILDREN = ['generator', 'tank', 'site']
const activeName = computed(() =>
  FLEET_CHILDREN.includes(String(route.name))
    ? 'fleet'
    : route.name === 'vehicle'
      ? 'vehicles'
      : route.name,
)
</script>

<template>
  <div class="shell">
    <a class="skip-link" href="#main">Skip to content</a>

    <header class="hdr">
      <div class="hdr__bar">
        <RouterLink to="/fleet" class="brand" aria-label="FuelPay, go to fleet">
          <AppLogo :size="26" />
        </RouterLink>

        <nav class="nav nav--wide" aria-label="Primary">
          <RouterLink
            v-for="item in NAV"
            :key="item.name"
            :to="{ name: item.name }"
            class="nav__link"
            :aria-current="activeName === item.name ? 'page' : undefined"
          >
            {{ item.label }}
            <span v-if="item.name === 'incidents' && incidents.alertCount" class="badge">
              {{ incidents.alertCount }}
            </span>
          </RouterLink>
        </nav>

        <div class="right">
          <LiveIndicator :updated-at="fleet.loadedAt" :error="fleet.error" />
          <ThemeToggle />
          <Button class="signout" size="small" @click="signOut">Sign out</Button>
          <button
            class="burger"
            type="button"
            :aria-expanded="open"
            aria-controls="nav-panel"
            aria-label="Menu"
            @click="open = !open"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
              <path v-if="!open" d="M4 7h16M4 12h16M4 17h16" />
              <path v-else d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
      </div>

      <Transition name="disclose">
        <div v-if="open" id="nav-panel" class="panel">
          <RouterLink
            v-for="item in NAV"
            :key="item.name"
            :to="{ name: item.name }"
            class="panel__link"
            :aria-current="activeName === item.name ? 'page' : undefined"
          >
            {{ item.label }}
            <span v-if="item.name === 'incidents' && incidents.alertCount" class="badge">
              {{ incidents.alertCount }}
            </span>
          </RouterLink>
          <button class="panel__link" type="button" @click="signOut">Sign out</button>
        </div>
      </Transition>
    </header>
    <DemoBanner />

    <main id="main" tabindex="-1"><slot /></main>

    <footer class="foot">
      <span>FuelPay</span>
      <span aria-hidden="true">·</span>
      <span>a product of</span>
      <img :src="resolved === 'dark' ? netpocWhite : netpocDark" alt="Πέτρος" class="foot__logo" />
    </footer>
  </div>
</template>

<style scoped>
.shell { min-height: 100vh; display: flex; flex-direction: column }
.shell > main { flex: 1 }

/* Netpoc glass-strong header over the page field. */
.hdr {
  position: sticky; top: 0; z-index: 30;
  background: var(--glass-strong-bg);
  -webkit-backdrop-filter: blur(24px) saturate(160%);
  backdrop-filter: blur(24px) saturate(160%);
  border-bottom: 1px solid var(--hairline);
}
/* A hairline of Ankara along the very top edge — the brand's signature, kept
   to 2px so it never competes with a status colour. */
.hdr::before {
  content: ''; position: absolute; inset: 0 0 auto; height: 2px;
  background: var(--np-ankara); opacity: 0.9;
}
.hdr__bar {
  display: flex; align-items: center; gap: 14px;
  max-width: 90rem; margin: 0 auto;
  padding: 8px 16px; min-height: 52px;
}
@media (min-width: 768px) { .hdr__bar { padding: 8px 24px; min-height: 56px; gap: 22px } }

.brand { display: flex; align-items: center; color: var(--ink); flex: none }

.nav { display: flex; align-items: center; gap: 2px }
.nav--wide { display: none }
@media (min-width: 768px) { .nav--wide { display: flex } }

.nav__link {
  position: relative;
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; min-height: 38px;
  font-size: 14px; font-weight: 600; color: var(--ink-muted); border-radius: 999px;
  transition: color var(--dur-micro) var(--ease-standard), background var(--dur-micro) var(--ease-standard);
}
.nav__link:hover { color: var(--ink); background: color-mix(in srgb, var(--ink) 6%, transparent) }
/* The active pill is driven by aria-current, so the accessible state and the
   visible state cannot drift apart. */
.nav__link[aria-current='page'] {
  color: var(--on-interactive);
  background: var(--interactive);
}

.right { margin-left: auto; display: flex; align-items: center; gap: 6px }
.signout { display: none }
@media (min-width: 768px) { .signout { display: inline-flex } }

.burger {
  display: inline-flex; align-items: center; justify-content: center;
  width: 36px; height: 36px; border-radius: 999px;
  background: transparent; border: 1px solid transparent; color: var(--ink-muted); cursor: pointer;
}
.burger:hover { background: var(--surface-sunken); color: var(--ink) }
@media (min-width: 768px) { .burger { display: none } }

.panel {
  display: flex; flex-direction: column; gap: 2px;
  padding: 6px 10px 12px; border-top: 1px solid var(--hairline);
}
@media (min-width: 768px) { .panel { display: none } }
.panel__link {
  display: flex; align-items: center; gap: 8px;
  padding: 11px 12px; min-height: 44px; border-radius: var(--radius-control);
  font: inherit; font-size: 15px; text-align: left;
  background: transparent; border: 0; color: var(--ink-muted); cursor: pointer;
}
.panel__link[aria-current='page'] {
  background: color-mix(in srgb, var(--interactive) 14%, transparent);
  color: var(--ink); font-weight: 700;
  box-shadow: inset 3px 0 0 var(--interactive);
}

.badge {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px;
  background: var(--status-critical); color: #fff;
  font-size: 11px; font-weight: 700;
}
/* On the saffron active pill the badge needs a ring to stay a separate shape. */
.nav__link[aria-current='page'] .badge { box-shadow: 0 0 0 2px var(--interactive) }

.foot {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: center; gap: 6px;
  padding: 18px 16px 22px; margin-top: 32px;
  border-top: 1px solid var(--hairline);
  font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--ink-subtle);
}
.foot__logo { height: 18px; width: auto; display: block }

.disclose-enter-active, .disclose-leave-active {
  transition: opacity var(--dur-surface) var(--ease-standard),
    transform var(--dur-surface) var(--ease-standard);
}
.disclose-enter-from, .disclose-leave-to { opacity: 0; transform: translateY(-6px) }

main:focus-visible { outline: none }
</style>
