<script setup lang="ts">
import { defineAsyncComponent, onMounted, watchEffect } from 'vue'
import { useRoute } from 'vue-router'
import { ConfigProvider, App as AntApp } from 'ant-design-vue'

import ApiKeyGate from '@/components/layout/ApiKeyGate.vue'
import AppShell from '@/components/layout/AppShell.vue'
import { useAuthStore } from '@/stores/auth'
import { useTheme } from '@/composables/useTheme'
import { antdThemeFor } from '@/theme/tokens'

// The admin console's root is its own chunk, loaded only on /admin.
const AdminRoot = defineAsyncComponent(() => import('@/components/admin/AdminRoot.vue'))

const auth = useAuthStore()
const route = useRoute()
const { resolved, apply } = useTheme()

// index.html stamps the attribute before first paint; this keeps it in step
// afterwards, including when the OS preference changes while the tab is open.
watchEffect(apply)

// A key persisted from a previous session still has to prove itself — it may
// have been revoked since. The admin console verifies its own session instead.
onMounted(() => {
  if (!route.path.startsWith('/admin')) auth.verify()
})
</script>

<template>
  <!--
    AntApp is not decoration: it provides the contextual message/notification
    API. Static `message.*` renders outside the ConfigProvider and would keep
    light-theme styling in dark mode.
  -->
  <ConfigProvider :theme="antdThemeFor(resolved)">
    <AntApp>
      <!-- The demo signup must render before any key exists. -->
      <AdminRoot v-if="route.meta.admin" />
      <RouterView v-else-if="route.meta.public" />
      <ApiKeyGate v-else-if="!auth.isAuthenticated && auth.status !== 'checking'" />
      <AppShell v-else>
        <RouterView v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </AppShell>
    </AntApp>
  </ConfigProvider>
</template>

<style>
.page-enter-active,
.page-leave-active {
  transition:
    opacity var(--dur-route) var(--ease-decelerate),
    transform var(--dur-route) var(--ease-decelerate);
}
.page-enter-from {
  opacity: 0;
  transform: translateY(8px);
}
.page-leave-to {
  opacity: 0;
}
</style>
