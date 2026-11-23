/**
 * Tank fill state.
 *
 * Pure so it can be tested and so the fleet store can classify rows without
 * mounting a component.
 */

/**
 * Named to match StatusKey in theme/tokens.ts. `watch` and `low` deliberately
 * share a hue and are separated by fill weight — a four-step traffic-light
 * palette cannot pass colourblind validation.
 */
export type TankState = 'ok' | 'watch' | 'low' | 'critical'

/** Below this share of capacity the site is hours from going dark. */
export const CRITICAL_PCT = 5

/**
 * Classify a tank against its OWN reorder threshold.
 *
 * The threshold is per-generator (20/25/30% across the seeded fleet), so a
 * fixed cut-off would mislabel half of them. `warn` is the approach to that
 * line rather than a second fixed number — a 30%-threshold unit starts warning
 * at 45%, a 20% one at 30%.
 */
export function tankState(fuelPct: number, reorderThresholdPct: number): TankState {
  if (fuelPct <= CRITICAL_PCT) return 'critical'
  if (fuelPct < reorderThresholdPct) return 'low'
  if (fuelPct < reorderThresholdPct * 1.5) return 'watch'
  return 'ok'
}

/** Human label. Paired with colour so state is never conveyed by hue alone. */
export const STATE_LABEL: Record<TankState, string> = {
  ok: 'OK',
  watch: 'Watch',
  low: 'Below reorder',
  critical: 'Critical',
}
