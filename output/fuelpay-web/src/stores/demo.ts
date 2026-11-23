/**
 * Demo-account state: expiry, limits, and whether data is still generating.
 *
 * Polls `/demo/status` fast while anything is backfilling — the wizard shows a
 * moving progress bar off it — and slowly otherwise, so the banner's day count
 * stays honest on a tab left open overnight.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { getDemoStatus } from '@/api/demo'
import type { DemoStatus } from '@/api/types'

const FAST_MS = 2_500
const SLOW_MS = 60_000

export const useDemoStore = defineStore('demo', () => {
  const status = ref<DemoStatus | null>(null)
  const error = ref<string | null>(null)
  let timer: ReturnType<typeof setTimeout> | null = null
  let watchers = 0

  const isDemo = computed(() => status.value?.is_demo ?? false)
  const canAddLocation = computed(() => {
    const s = status.value
    return !!s?.limits && s.usage.locations < s.limits.max_locations
  })
  const canAddTractor = computed(() => {
    const s = status.value
    return !!s?.limits && s.usage.tractors < s.limits.max_tractors
  })
  const hasTractors = computed(() => (status.value?.usage.tractors ?? 0) > 0)

  async function load() {
    try {
      status.value = await getDemoStatus()
      error.value = null
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : 'Could not load demo status.'
    }
    return status.value
  }

  function schedule() {
    if (timer) clearTimeout(timer)
    if (!watchers) return
    timer = setTimeout(
      async () => {
        await load()
        schedule()
      },
      status.value?.generating ? FAST_MS : SLOW_MS,
    )
  }

  /** Start polling; returns the matching stop. Reference-counted so the
   *  banner and the wizard can both hold it without fighting. */
  function watch() {
    watchers += 1
    load().then(schedule)
    return () => {
      watchers = Math.max(0, watchers - 1)
      if (!watchers && timer) clearTimeout(timer)
    }
  }

  function entity(id: string) {
    return status.value?.entities.find((e) => e.id === id)
  }

  function reset() {
    status.value = null
  }

  return {
    status,
    error,
    isDemo,
    canAddLocation,
    canAddTractor,
    hasTractors,
    load,
    watch,
    entity,
    reset,
  }
})
