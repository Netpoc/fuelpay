/**
 * API key handling.
 *
 * The key lives in localStorage, which is honestly stated: it is readable by
 * any script that gets injected into this page. That is acceptable here
 * because the demo key is rotatable through /v1/admin/api-keys and grants
 * access only to simulated data. A real deployment should move to a session
 * cookie issued by a backend-for-frontend, so the browser never holds a
 * long-lived tenant credential at all.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ApiError, onUnauthorized, setApiKey } from '@/api/client'
import { getSummary } from '@/api/fleet'

const STORAGE_KEY = 'fuelpay.apiKey'

export type AuthStatus = 'unknown' | 'checking' | 'valid' | 'invalid'

export const useAuthStore = defineStore('auth', () => {
  const apiKey = ref<string | null>(
    localStorage.getItem(STORAGE_KEY) ?? import.meta.env.VITE_FUELPAY_API_KEY ?? null,
  )
  const status = ref<AuthStatus>('unknown')
  const error = ref<string | null>(null)

  setApiKey(apiKey.value)

  const isAuthenticated = computed(() => status.value === 'valid')

  /**
   * Confirm the key works.
   *
   * /v1/summary is the cheapest authenticated endpoint that proves the key
   * resolves to an organisation — no parameters, one row of aggregates.
   */
  async function verify(): Promise<boolean> {
    if (!apiKey.value) {
      status.value = 'invalid'
      return false
    }

    status.value = 'checking'
    error.value = null
    try {
      await getSummary()
      status.value = 'valid'
      return true
    } catch (caught) {
      status.value = 'invalid'
      error.value =
        caught instanceof ApiError && caught.isAuthFailure
          ? 'That key was not accepted.'
          : caught instanceof Error
            ? caught.message
            : 'Could not reach the service.'
      return false
    }
  }

  async function setKey(key: string): Promise<boolean> {
    apiKey.value = key.trim()
    localStorage.setItem(STORAGE_KEY, apiKey.value)
    setApiKey(apiKey.value)
    return verify()
  }

  function clear() {
    apiKey.value = null
    localStorage.removeItem(STORAGE_KEY)
    setApiKey(null)
    status.value = 'invalid'
  }

  // A 401 from any request anywhere drops us back to the gate. Without this
  // every caller would need its own auth-failure branch.
  onUnauthorized(() => {
    if (status.value === 'valid') {
      status.value = 'invalid'
      error.value = 'The key stopped working — it may have been revoked.'
    }
  })

  return { apiKey, status, error, isAuthenticated, verify, setKey, clear }
})
