/**
 * A site's daily fuel flow, summed from its tanks.
 *
 * Pure, and separated from the chart because three of the summing rules are
 * easy to get wrong in ways that produce a plausible-looking chart:
 *
 * - `transferred_l` must NOT be summed across tiers. A bulk tank's transfer is
 *   fuel going OUT to a day tank; the day tank records the SAME litres coming
 *   in. Adding both double-counts every litre that moved on site.
 * - `consumed_l` is a day-tank figure. Bulk feeds no engine and is documented
 *   as always zero, so filtering by tier states the intent rather than relying
 *   on that staying true.
 * - `samples` must NOT be summed. Coverage is per tank, so the honest figure
 *   for a site is the WORST of its tanks, not the total.
 */

import type { DailyTankFlow, TankConsumption } from '@/api/types'

/** One reading per 5 simulated minutes. Shared with the tank page. */
export const EXPECTED_SAMPLES_PER_DAY = 288

export interface SiteFlowDay {
  day: string
  /** Burned by engines. Day tanks only. */
  consumed_l: number
  /** Delivered by tanker into bulk. */
  delivered_l: number
  /** Bulk -> day. Counted on the bulk side only, or it doubles. */
  transferred_l: number
  /** Observed theft. Either tier. */
  drained_l: number
  /** Missing across an outage — NOT established theft. Kept separate. */
  unverified_loss_l: number
  /** Worst per-tank coverage on the day, 0..1. */
  coverage: number
  /**
   * True when no tank on site produced a single reading. The bars must render
   * as a gap, never as zeroes: a zero bar asserts no fuel moved, a gap says
   * nobody was looking. Conflating them is the same error as joining a line
   * across a sensor outage.
   */
  unobserved: boolean
}

export function siteFlowDays(flows: TankConsumption[]): SiteFlowDay[] {
  if (!flows.length) return []

  const bulk = flows.filter((flow) => flow.kind === 'BULK')
  const day = flows.filter((flow) => flow.kind === 'DAY')

  const index = (list: TankConsumption[]) => {
    const map = new Map<string, DailyTankFlow[]>()
    for (const flow of list) {
      for (const entry of flow.days) {
        const list = map.get(entry.day) ?? []
        list.push(entry)
        map.set(entry.day, list)
      }
    }
    return map
  }

  const bulkDays = index(bulk)
  const dayDays = index(day)
  const allDays = index(flows)

  const sum = (entries: DailyTankFlow[] | undefined, key: keyof DailyTankFlow) =>
    (entries ?? []).reduce((total, entry) => total + (entry[key] as number), 0)

  // Union of every day any tank reported, ascending. Days with no activity are
  // absent from the API by design, so the axis is built from what exists.
  const days = [...new Set(allDays.keys())].sort()

  return days.map((key) => {
    const entries = allDays.get(key) ?? []
    // A tank that reported nothing at all on this day is absent from `entries`,
    // so coverage has to be measured against the number of tanks on site.
    const coverages = flows.map((flow) => {
      const entry = flow.days.find((candidate) => candidate.day === key)
      return Math.min(1, (entry?.samples ?? 0) / EXPECTED_SAMPLES_PER_DAY)
    })

    return {
      day: key,
      consumed_l: sum(dayDays.get(key), 'consumed_l'),
      delivered_l: sum(bulkDays.get(key), 'delivered_l'),
      transferred_l: sum(bulkDays.get(key), 'transferred_l'),
      drained_l: sum(entries, 'drained_l'),
      unverified_loss_l: sum(entries, 'unverified_loss_l'),
      coverage: Math.min(...coverages),
      unobserved: entries.every((entry) => entry.samples === 0),
    }
  })
}

export interface SiteFlowTotals {
  consumed_l: number
  delivered_l: number
  transferred_l: number
  drained_l: number
  unverified_loss_l: number
  /** Days in the window where nothing was observed at all. */
  unobservedDays: number
}

export function siteFlowTotals(days: SiteFlowDay[]): SiteFlowTotals {
  return days.reduce<SiteFlowTotals>(
    (totals, day) => ({
      consumed_l: totals.consumed_l + day.consumed_l,
      delivered_l: totals.delivered_l + day.delivered_l,
      transferred_l: totals.transferred_l + day.transferred_l,
      drained_l: totals.drained_l + day.drained_l,
      unverified_loss_l: totals.unverified_loss_l + day.unverified_loss_l,
      unobservedDays: totals.unobservedDays + (day.unobserved ? 1 : 0),
    }),
    {
      consumed_l: 0,
      delivered_l: 0,
      transferred_l: 0,
      drained_l: 0,
      unverified_loss_l: 0,
      unobservedDays: 0,
    },
  )
}
