/**
 * Admin console session.
 *
 * The token lives in sessionStorage, not localStorage: it dies with the tab,
 * which suits an operator console better than a remembered login. It is
 * readable by injected script like the tenant key; a cookie session is the
 * hardening step if the console is ever exposed beyond the team.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError } from '@/api/client'
import { login as apiLogin, logout as apiLogout, me, onAdminUnauthorized, setAdminToken } from '@/api/admin'
import type { Me } from '@/api/adminTypes'

const STORAGE_KEY = 'fuelpay.adminToken'

function read(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}
function write(value: string | null) {
  try {
    if (value) sessionStorage.setItem(STORAGE_KEY, value)
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private mode: the session simply won't survive a reload */
  }
}

export const useAdminAuthStore = defineStore('adminAuth', () => {
  const token = ref<string | null>(read())
  const profile = ref<Me | null>(null)
  const status = ref<'unknown' | 'checking' | 'valid' | 'invalid'>('unknown')
  const error = ref<string | null>(null)

  setAdminToken(token.value)

  const isAuthenticated = computed(() => status.value === 'valid')
  const isOwner = computed(() => profile.value?.admin.role === 'OWNER')

  async function verify() {
    if (!token.value) {
      status.value = 'invalid'
      return false
    }
    status.value = 'checking'
    try {
      profile.value = await me()
      status.value = 'valid'
      return true
    } catch {
      status.value = 'invalid'
      return false
    }
  }

  async function signIn(email: string, password: string) {
    error.value = null
    try {
      const result = await apiLogin(email, password)
      token.value = result.token
      write(result.token)
      setAdminToken(result.token)
      return verify()
    } catch (caught) {
      error.value =
        caught instanceof ApiError ? caught.detail : 'Could not reach the service.'
      status.value = 'invalid'
      return false
    }
  }

  async function signOut() {
    try {
      if (token.value) await apiLogout()
    } catch {
      /* already expired is fine */
    }
    token.value = null
    profile.value = null
    write(null)
    setAdminToken(null)
    status.value = 'invalid'
  }

  onAdminUnauthorized(() => {
    if (status.value === 'valid') error.value = 'Your session ended. Sign in again.'
    token.value = null
    write(null)
    setAdminToken(null)
    status.value = 'invalid'
  })

  return { token, profile, status, error, isAuthenticated, isOwner, verify, signIn, signOut }
})
