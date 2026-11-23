import { theme } from 'ant-design-vue'
import type { ThemeConfig } from 'ant-design-vue/es/config-provider/context'

/**
 * Values that JavaScript needs.
 *
 * CSS custom properties in assets/main.css are the source of truth for
 * anything the browser paints. This file exists for the three consumers that
 * cannot read a CSS variable: the ECharts canvas, antd's ConfigProvider, and
 * the tank's SVG gradient stops. Keep the two in sync — theme/tokens.spec.ts
 * asserts they have not drifted.
 *
 * Mirrors ../../fuelpay-brand/tokens/color.json, which is machine-validated by
 * that package's `validate-palettes.mjs`.
 */

export type Mode = 'light' | 'dark'
export type StatusKey = 'ok' | 'watch' | 'low' | 'critical'

/**
 * Brand is identity ONLY and is never a status.
 *
 * The previous system had brand, ok and info all set to the same teal, which
 * meant a healthy tank and the company logo were indistinguishable — and any
 * brand change would silently repaint every status in the product.
 */
export const BRAND = {
  navy: '#0B2545',
  navyDeep: '#071A33',
  amber: '#F2A93B',
  amber600: '#D98E1F',
  amber800: '#8A5A08',
} as const

/**
 * Status marks, per theme.
 *
 * THREE hues, not four. A four-step traffic-light ramp cannot pass colourblind
 * validation: the two ambers separate by only ΔE 1.3 under deuteranopia, well
 * under the floor of 6 — they are metamers. `watch` and `low` therefore share
 * a hue and are distinguished by FILL WEIGHT plus their always-present text
 * label (see STATE_LABEL in components/tank/state.ts).
 */
export const STATUS = {
  light: {
    ok: '#0E7C5A',
    watch: '#D2760F',
    low: '#D2760F',
    critical: '#96161F',
  },
  dark: {
    ok: '#2FA985',
    watch: '#B78A20',
    low: '#B78A20',
    critical: '#CC2A46',
  },
} as const satisfies Record<Mode, Record<StatusKey, string>>

/** Status colours legible as TEXT (the marks above are tuned for fills). */
export const STATUS_TEXT = {
  light: {
    ok: '#0B6448',
    watch: '#8A5A08',
    low: '#8A5A08',
    critical: '#8E1420',
  },
  dark: {
    ok: '#45C39C',
    watch: '#E0B554',
    low: '#E0B554',
    critical: '#F58095',
  },
} as const satisfies Record<Mode, Record<StatusKey, string>>

/**
 * How each status is filled. This is the second channel that lets `watch` and
 * `low` share a hue without becoming indistinguishable.
 */
export const STATUS_WEIGHT = {
  ok: 'soft',
  watch: 'soft',
  low: 'solid',
  critical: 'solid',
} as const satisfies Record<StatusKey, 'soft' | 'solid'>

/** Ant Design theme, per mode. */
export function antdThemeFor(mode: Mode): ThemeConfig {
  return {
    // `theme` must come from the package root — `darkAlgorithm` is not a named
    // export of ant-design-vue/es/theme, it lives on the default export, and a
    // named import fails at runtime.
    algorithm: mode === 'dark' ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      // Two values: the light navy is unreadable on a dark field once antd
      // derives its hover and active states from it.
      colorPrimary: mode === 'dark' ? '#3F8AD8' : '#123A63',
      colorSuccess: STATUS[mode].ok,
      colorWarning: STATUS[mode].watch,
      colorError: STATUS[mode].critical,
      colorBgBase: mode === 'dark' ? '#0B1420' : '#F6F8FA',
      colorTextBase: mode === 'dark' ? '#E9EFF6' : '#0B1B2B',
      borderRadius: 6,
      fontFamily:
        "'Inter Variable', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
      fontSize: 14,
    },
  }
}
