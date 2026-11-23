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
@media (min-width: 960px) { .layout { grid-template-columns: 232px minmax(0, 1fr) } }

/* Navy in both themes: the band that says "you are operating the platform". */
.rail { background: #0b2545; color: #e9eff6; display: flex; flex-direction: column }
@media (min-width: 960px) { .rail { position: sticky; top: 0; height: 100vh } }
.rail__top { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px }
.brand { display: flex; align-items: center; gap: 10px; color: #e9eff6 }
.badge {
  padding: 1px 8px; border-radius: 999px; background: #f2a93b; color: #0b2545;
  font-size: 10px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
}
.burger {
  display: inline-flex; align-items: center; justify-content: center; width: 36px; height: 36px;
  background: transparent; border: 0; color: #e9eff6; cursor: pointer; border-radius: var(--radius-control);
}
@media (min-width: 960px) { .burger { display: none } }

.nav { display: none; flex-direction: column; gap: 2px; padding: 4px 10px 10px }
.rail.open .nav { display: flex }
@media (min-width: 960px) { .nav { display: flex; padding-top: 12px } }
.nav__link {
  display: flex; align-items: center; min-height: 38px; padding: 8px 12px;
  border-radius: var(--radius-control); color: #9aabbe; font-size: 14px;
}
.nav__link:hover { color: #e9eff6; background: rgba(233, 239, 246, 0.06) }
.nav__link[aria-current='page'] { color: #0b2545; background: #f2a93b; font-weight: 600 }

.rail__foot {
  display: none; margin-top: auto; padding: 14px 16px; border-top: 1px solid rgba(233, 239, 246, 0.12);
  flex-direction: column; gap: 10px;
}
.rail.open .rail__foot { display: flex }
@media (min-width: 960px) { .rail__foot { display: flex } }
.who { display: flex; flex-direction: column; min-width: 0 }
.who__name { font-weight: 600; font-size: 13px }
.who__meta { font-size: 11px; color: #9aabbe; overflow: hidden; text-overflow: ellipsis; white-space: nowrap }
.foot__actions { display: flex; align-items: center; justify-content: space-between; color: #e9eff6 }

.signout {
  padding: 4px 12px; min-height: 30px; font: inherit; font-size: 13px; cursor: pointer;
  color: #e9eff6; background: transparent;
  border: 1px solid rgba(233, 239, 246, 0.35); border-radius: var(--radius-control);
}
.signout:hover { border-color: #f2a93b; color: #f2a93b }
.main { min-width: 0 }
.main:focus-visible { outline: none }
</style>
