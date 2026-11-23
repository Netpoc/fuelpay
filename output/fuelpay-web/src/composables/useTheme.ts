import { computed } from 'vue'
import { createSharedComposable, usePreferredDark, useStorage } from '@vueuse/core'

import type { Mode } from '@/theme/tokens'

export type ThemePreference = 'auto' | Mode

export const THEME_STORAGE_KEY = 'fuelpay.theme'

/**
 * Theme preference, resolved to a concrete mode.
 *
 * Tri-state on purpose: "auto" is a real answer, not an absence of one, and a
 * monitoring product gets used both in a bright office and on a night shift.
 *
 * The attribute is written manually rather than through `useColorMode`'s own
 * selector handling, because we need storage to keep "auto" while the DOM
 * always carries a concrete "light" or "dark" — the CSS has no rule for an
 * attribute value of "auto", and Tailwind's dark variant is bound to the
 * literal string.
 *
 * The FIRST paint is handled by a blocking script in index.html; this
 * composable takes over once Vue mounts. Both must agree on the storage key
 * and the attribute name.
 */
export const useTheme = createSharedComposable(() => {
  const preference = useStorage<ThemePreference>(THEME_STORAGE_KEY, 'auto')
  const prefersDark = usePreferredDark()

  const resolved = computed<Mode>(() =>
    preference.value === 'auto' ? (prefersDark.value ? 'dark' : 'light') : preference.value,
  )

  const apply = () => {
    const root = document.documentElement
    root.dataset.theme = resolved.value
    root.style.colorScheme = resolved.value
  }

  /** auto → light → dark → auto. */
  const cycle = () => {
    preference.value =
      preference.value === 'auto' ? 'light' : preference.value === 'light' ? 'dark' : 'auto'
  }

  const set = (next: ThemePreference) => {
    preference.value = next
  }

  return { preference, resolved, prefersDark, apply, cycle, set }
})
