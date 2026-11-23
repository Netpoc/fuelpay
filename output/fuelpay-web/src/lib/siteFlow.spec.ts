import { describe, expect, it } from 'vitest'

import { siteFlowDays, siteFlowTotals, EXPECTED_SAMPLES_PER_DAY } from './siteFlow'
import type { DailyTankFlow, TankConsumption } from '@/api/types'

const DAY_1 = '2026-08-25T00:00:00Z'
const DAY_2 = '2026-08-26T00:00:00Z'

function flow(
  kind: 'BULK' | 'DAY',
  days: Partial<DailyTankFlow>[],
  name = `${kind} tank`,
): TankConsumption {
  const full = days.map((day) => ({
    day: DAY_1,
    consumed_l: 0,
    transferred_l: 0,
    delivered_l: 0,
    drained_l: 0,
    unverified_loss_l: 0,
    samples: EXPECTED_SAMPLES_PER_DAY,
    ...day,
  }))
  return {
    tank_id: `${kind}-${name}`,
    tank_name: name,
    kind,
    capacity_l: kind === 'BULK' ? 5000 : 1000,
    days: full,
    total_consumed_l: 0,
    total_transferred_l: 0,
    total_delivered_l: 0,
    total_drained_l: 0,
    total_unverified_loss_l: 0,
  }
}

describe('siteFlowDays', () => {
  it('takes transfer from the bulk side only', () => {
    // The same 400 L, recorded twice: out of bulk and into the day tank.
    // Summing both would report 800 L moving on a site where 400 L moved.
    const days = siteFlowDays([
      flow('BULK', [{ day: DAY_1, transferred_l: 400 }]),
      flow('DAY', [{ day: DAY_1, transferred_l: 400 }]),
    ])

    expect(days).toHaveLength(1)
    expect(days[0]!.transferred_l).toBe(400)
  })

  it('takes burn from day tanks only', () => {
    const days = siteFlowDays([
      flow('BULK', [{ day: DAY_1, consumed_l: 0 }]),
      flow('DAY', [{ day: DAY_1, consumed_l: 120 }]),
    ])

    expect(days[0]!.consumed_l).toBe(120)
  })

  it('takes deliveries from bulk, where the tanker actually pumps', () => {
    const days = siteFlowDays([
      flow('BULK', [{ day: DAY_1, delivered_l: 4000 }]),
      flow('DAY', [{ day: DAY_1, delivered_l: 0 }]),
    ])

    expect(days[0]!.delivered_l).toBe(4000)
  })

  it('sums losses across BOTH tiers', () => {
    // Theft happens in either tier, and the simulator weights it toward bulk.
    const days = siteFlowDays([
      flow('BULK', [{ day: DAY_1, drained_l: 300 }]),
      flow('DAY', [{ day: DAY_1, drained_l: 40 }]),
    ])

    expect(days[0]!.drained_l).toBe(340)
  })

  it('keeps unverified loss apart from an observed drain', () => {
    const days = siteFlowDays([
      flow('BULK', [{ day: DAY_1, drained_l: 300, unverified_loss_l: 120 }]),
    ])

    expect(days[0]!.drained_l).toBe(300)
    expect(days[0]!.unverified_loss_l).toBe(120)
  })

  it('reports the WORST tank coverage, never the sum', () => {
    // Summing samples across two tanks would read as 100% coverage on a day
    // when one of them saw half of it.
    const days = siteFlowDays([
      flow('BULK', [{ day: DAY_1, samples: EXPECTED_SAMPLES_PER_DAY }]),
      flow('DAY', [{ day: DAY_1, samples: EXPECTED_SAMPLES_PER_DAY / 2 }]),
    ])

    expect(days[0]!.coverage).toBe(0.5)
  })

  it('counts a tank absent from a day as zero coverage', () => {
    const days = siteFlowDays([
      flow('BULK', [{ day: DAY_1 }]),
      flow('DAY', [{ day: DAY_2 }], 'day-a'),
    ])

    const first = days.find((day) => day.day === DAY_1)!
    expect(first.coverage).toBe(0)
  })

  it('marks a day nobody observed, so it can be drawn as a gap not a zero', () => {
    const days = siteFlowDays([flow('BULK', [{ day: DAY_1, samples: 0, delivered_l: 0 }])])

    expect(days[0]!.unobserved).toBe(true)
  })

  it('does not mark a genuinely quiet but observed day as unobserved', () => {
    // Nothing moved, but the sensor was watching the whole time. That is a real
    // zero and must render as a zero bar, not a hole.
    const days = siteFlowDays([flow('BULK', [{ day: DAY_1 }])])

    expect(days[0]!.unobserved).toBe(false)
    expect(days[0]!.coverage).toBe(1)
  })

  it('unions days across tanks, ascending', () => {
    const days = siteFlowDays([
      flow('BULK', [{ day: DAY_2 }]),
      flow('DAY', [{ day: DAY_1 }], 'day-a'),
    ])

    expect(days.map((day) => day.day)).toEqual([DAY_1, DAY_2])
  })

  it('returns nothing for no tanks', () => {
    expect(siteFlowDays([])).toEqual([])
  })
})

describe('siteFlowTotals', () => {
  it('adds the days up and counts the unobserved ones', () => {
    const days = siteFlowDays([
      flow('BULK', [
        { day: DAY_1, delivered_l: 4000, drained_l: 100 },
        { day: DAY_2, samples: 0 },
      ]),
      flow('DAY', [{ day: DAY_1, consumed_l: 200 }], 'day-a'),
    ])

    const totals = siteFlowTotals(days)
    expect(totals.delivered_l).toBe(4000)
    expect(totals.consumed_l).toBe(200)
    expect(totals.drained_l).toBe(100)
    expect(totals.unobservedDays).toBe(1)
  })
})
