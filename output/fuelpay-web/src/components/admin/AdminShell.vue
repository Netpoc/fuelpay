<script setup lang="ts">
/**
 * Admin chrome: a side rail on desktop, a disclosure on mobile, and a navy
 * "Admin" band so the console is never mistaken for a tenant's view.
 */
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import AppLogo from '@/components/ui/AppLogo.vue'
import ThemeToggle from '@/components/ui/ThemeToggle.vue'
import { useAdminAuthStore } from '@/stores/adminAuth'

const admin = useAdminAuthStore()
const route = useRoute()
const open = ref(false)
watch(() => route.fullPath, () => (open.value = false))

const NAV = computed(() =>
  [
    { name: 'admin', label: 'Overview', match: ['admin'] },
    { name: 'admin-tenants', label: 'Tenants', match: ['admin-tenants', 'admin-tenant'] },
    { name: 'admin-coupons', label: 'Coupons', match: ['admin-coupons', 'admin-coupon'] },
    { name: 'admin-system', label: 'System', match: ['admin-system'] },
    { name: 'admin-admins', label: 'Admins', match: ['admin-admins'], owner: true },
    { name: 'admin-audit', label: 'Audit log', match: ['admin-audit'] },
  ].filter((item) => !item.owner || admin.isOwner),
)
const current = (match: string[]) => match.includes(String(route.name))
</script>

<template>
  <div class="layout">
    <a class="skip-link" href="#admin-main">Skip to content</a>
    <aside class="rail" :class="{ open }">
      <div class="rail__top">
        <RouterLink to="/admin" class="brand" aria-label="Admin overview">
          <AppLogo :size="24" reversed />
          <span class="badge">Admin</span>
        </RouterLink>
        <button
          class="burger"
          type="button"
          :aria-expanded="open"
          aria-controls="admin-nav"
          aria-label="Menu"
          @click="open = !open"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
            <path v-if="!open" d="M4 7h16M4 12h16M4 17h16" />
            <path v-else d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </div>
      <nav id="admin-nav" class="nav" aria-label="Admin">
        <RouterLink
          v-for="item in NAV"
          :key="item.name"
          :to="{ name: item.name }"
          class="nav__link"
          :aria-current="current(item.match) ? 'page' : undefined"
        >
          {{ item.label }}
        </RouterLink>
      </nav>
      <div class="rail__foot">
        <div class="who">
          <span class="who__name">{{ admin.profile?.admin.name }}</span>
          <span class="who__meta">{{ admin.profile?.admin.email }} · {{ admin.profile?.admin.role.toLowerCase() }}</span>
        </div>
        <div class="foot__actions">
          <ThemeToggle />
          <button type="button" class="signout" @click="admin.signOut()">Sign out</button>
        </div>
      </div>
    </aside>
    <main id="admin-main" class="main" tabindex="-1"><slot /></main>
  </div>
</template>

<style scoped>
.layout { min-height: 100vh; display: grid; grid-template-columns: 1fr; background: var(--surface) }
@media (min-width: 960px) { .layout { grid-template-columns: 240px minmax(0, 1fr) } }

/* Night rail in both themes: the band that says "you are operating the
   platform". An Ankara edge runs down its inner side. */
.rail {
  position: relative;
  background: var(--np-night-3); color: var(--np-ivory);
  display: flex; flex-direction: column;
}
.rail::after {
  content: ''; position: absolute; top: 0; bottom: 0; right: 0; width: 3px;
  background: linear-gradient(180deg, var(--np-saffron), var(--np-coral) 45%, var(--np-violet));
}
@media (max-width: 959px) { .rail::after { inset: auto 0 0 0; width: auto; height: 2px; background: var(--np-ankara) } }
@media (min-width: 960px) { .rail { position: sticky; top: 0; height: 100vh } }
.rail__top { display: flex; align-items: center; justify-content: space-between; padding: 16px 16px }
.brand { display: flex; align-items: center; gap: 10px; color: var(--np-ivory) }
.badge {
  padding: 2px 9px; border-radius: 999px; background: var(--np-saffron); color: var(--np-void);
  font-family: var(--font-mono); font-size: 10px; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
}
.burger {
  display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px;
  background: transparent; border: 0; color: var(--np-ivory); cursor: pointer; border-radius: 999px;
}
@media (min-width: 960px) { .burger { display: none } }

.nav { display: none; flex-direction: column; gap: 3px; padding: 4px 12px 10px }
.rail.open .nav { display: flex }
@media (min-width: 960px) { .nav { display: flex; padding-top: 12px } }
.nav__link {
  display: flex; align-items: center; min-height: 38px; padding: 8px 14px;
  border-radius: 999px; color: var(--np-mist); font-size: 14px; font-weight: 600;
  transition: background var(--dur-micro) var(--ease-standard), color var(--dur-micro) var(--ease-standard);
}
.nav__link:hover { color: var(--np-ivory); background: rgb(245 242 234 / 7%) }
.nav__link[aria-current='page'] { color: var(--np-void); background: var(--np-saffron); font-weight: 700 }

.rail__foot {
  display: none; margin-top: auto; padding: 14px 16px; border-top: 1px solid rgb(245 242 234 / 12%);
  flex-direction: column; gap: 10px;
}
.rail.open .rail__foot { display: flex }
@media (min-width: 960px) { .rail__foot { display: flex } }
.who { display: flex; flex-direction: column; min-width: 0 }
.who__name { font-weight: 700; font-size: 13px }
.who__meta { font-size: 11px; color: var(--np-mist); overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.foot__actions { display: flex; align-items: center; justify-content: space-between; color: var(--np-ivory) }

.signout {
  padding: 4px 14px; min-height: 30px; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
  color: var(--np-ivory); background: transparent;
  border: 1px solid rgb(245 242 234 / 30%); border-radius: 999px;
  transition: border-color var(--dur-micro) var(--ease-standard), color var(--dur-micro) var(--ease-standard);
}
.signout:hover { border-color: var(--np-saffron); color: var(--np-saffron) }
.main { min-width: 0 }
.main:focus-visible { outline: none }
</style>
