<script setup lang="ts">
/**
 * The admin console's own gate and shell. Rendered by App.vue for any
 * `meta.admin` route, in place of the tenant key gate and app shell — the two
 * consoles share a design system and nothing else.
 */
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

import AdminLogin from './AdminLogin.vue'
import AdminShell from './AdminShell.vue'
import { useAdminAuthStore } from '@/stores/adminAuth'

const admin = useAdminAuthStore()
const route = useRoute()

onMounted(() => {
  if (admin.status === 'unknown') admin.verify()
})

const forbidden = computed(() => route.meta.owner && !admin.isOwner)
</script>

<template>
  <div v-if="admin.status === 'unknown' || admin.status === 'checking'" class="boot" role="status">
    Checking session…
  </div>
  <AdminLogin v-else-if="!admin.isAuthenticated" />
  <AdminShell v-else>
    <div v-if="forbidden" class="denied">
      <h1>Owners only</h1>
      <p>This page manages other admins. Ask an owner if you need a change here.</p>
    </div>
    <RouterView v-else v-slot="{ Component }">
      <Transition name="page" mode="out-in">
        <component :is="Component" />
      </Transition>
    </RouterView>
  </AdminShell>
</template>

<style scoped>
.boot { display: grid; place-items: center; min-height: 100vh; color: var(--ink-muted); font-size: 13px }
.denied { max-width: 40rem; margin: 48px auto; padding: 0 16px }
.denied h1 { font-size: 20px; margin: 0 0 6px }
.denied p { color: var(--ink-muted); margin: 0 }
</style>
