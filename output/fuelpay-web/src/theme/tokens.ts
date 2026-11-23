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
  // Netpoc palette — FuelPay is a Netpoc product and wears its system.
  void: '#080714',
  night: '#0B0A1A',
  night2: '#14122B',
  night3: '#1D1A3A',
  ivory: '#F5F2EA',
  mist: '#B6B2CF',
  saffron: '#F7B733',
  coral: '#FF5E5B',
  terracotta: '#E06236',
  terracottaDeep: '#A33F1B',
  emerald: '#1FB58F',
  violet: '#A64BF4',
  indigo: '#5B6BFF',
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
    watch: '#C9700C',
    low: '#C9700C',
    critical: '#A3172A',
  },
  dark: {
    ok: '#22A98A',
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
    ok: '#3FD0A8',
    watch: '#F7B733',
    low: '#F7B733',
    critical: '#FF7F8A',
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
      // Saffron on night (void text on the fill, 11.2:1). Saffron is
      // illegible on ivory, so light mode uses deep terracotta — same Ankara
      // family, white text 6.3:1.
      colorPrimary: mode === 'dark' ? BRAND.saffron : BRAND.terracottaDeep,
      colorTextLightSolid: mode === 'dark' ? BRAND.void : '#FFFFFF',
      colorLink: mode === 'dark' ? BRAND.saffron : BRAND.terracottaDeep,
      colorInfo: mode === 'dark' ? '#7480FF' : '#4450D8',
      colorSuccess: STATUS[mode].ok,
      colorWarning: STATUS[mode].watch,
      colorError: STATUS[mode].critical,
      colorBgBase: mode === 'dark' ? BRAND.night : '#F7F4EC',
      colorBgContainer: mode === 'dark' ? BRAND.night2 : '#FFFDF8',
      colorBgElevated: mode === 'dark' ? BRAND.night3 : '#FFFDF8',
      colorTextBase: mode === 'dark' ? BRAND.ivory : BRAND.night2,
      colorBorder: mode === 'dark' ? 'rgba(245,242,234,0.16)' : '#D2C8B3',
      colorBorderSecondary: mode === 'dark' ? 'rgba(245,242,234,0.09)' : '#E4DDCD',
      borderRadius: 10,
      fontFamily: "'Manrope Variable', 'Manrope', ui-sans-serif, system-ui, sans-serif",
      fontSize: 14,
    },
    components: {
      // Netpoc buttons are pills.
      Button: { borderRadius: 999, borderRadiusLG: 999, borderRadiusSM: 999 },
    },
  }
}
