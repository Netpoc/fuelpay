import { describe, expect, it } from 'vitest'

import type { Event, EventType } from '@/api/types'
import { groupIncidents, isAlerting, liveAlerts } from './incidents'

let seq = 0
function ev(
  type: EventType,
  minutesAgo: number,
  volume: number | null = null,
  generator: string | null = 'gen-1',
  tank: string | null = null,
): Event {
  const base = Date.parse('2026-08-03T12:00:00Z')
  return {
    id: `e${seq++}`,
    generator_id: generator,
    tank_id: tank,
    event_type: type,
    occurred_at: new Date(base - minutesAgo * 60_000).toISOString(),
    volume_l: volume,
    fuel_level_l: 100,
    detail: {},
  }
}

/** A site-level event: bulk storage, so no generator. */
const siteEv = (
  type: EventType,
  minutesAgo: number,
  volume: number | null = null,
  tank = 'tank-bulk-1',
) => ev(type, minutesAgo, volume, null, tank)

describe('groupIncidents', () => {
  it('collapses a siphon series into one incident', () => {
    // A theft emits one event per tick as the pump works. Six markers stacked
    // on a chart would misrepresent one incident as six.
    const events = [
      ev('SUSPECTED_DRAIN', 30, -5),
      ev('SUSPECTED_DRAIN', 25, -5),
      ev('SUSPECTED_DRAIN', 20, -5),
      ev('SUSPECTED_DRAIN', 15, -5),
    ]
    const incidents = groupIncidents(events)
    const incident = incidents[0]!
    const rest = incidents.slice(1)

    expect(rest).toHaveLength(0)
    expect(incident.count).toBe(4)
    expect(incident.volume_l).toBe(-20)
    expect(incident.occurred_at).toBe(events[0]!.occurred_at)
    expect(incident.ended_at).toBe(events[3]!.occurred_at)
  })

  it('keeps separate thefts separate', () => {
    // Hours apart is two incidents, not one long one.
    const incidents = groupIncidents([
      ev('SUSPECTED_DRAIN', 600, -50),
      ev('SUSPECTED_DRAIN', 20, -60),
    ])
    expect(incidents).toHaveLength(2)
  })

  it('does not merge across generators', () => {
    const incidents = groupIncidents([
      ev('SUSPECTED_DRAIN', 20, -5, 'gen-1'),
      ev('SUSPECTED_DRAIN', 19, -5, 'gen-2'),
    ])
    expect(incidents).toHaveLength(2)
  })

  it('does not merge different event types', () => {
    const incidents = groupIncidents([ev('LOW_FUEL', 21), ev('REFILL', 20, 300)])
    expect(incidents).toHaveLength(2)
  })

  it('returns newest first', () => {
    const incidents = groupIncidents([ev('REFILL', 500, 100), ev('LOW_FUEL', 5)])
    expect(incidents[0]!.event_type).toBe('LOW_FUEL')
  })

  it('handles an empty list', () => {
    expect(groupIncidents([])).toEqual([])
  })

  it('leaves a null volume null rather than turning it into zero', () => {
    // LOW_FUEL carries no volume; a 0 would render as "0 L" and imply a
    // measurement that was never taken.
    expect(groupIncidents([ev('LOW_FUEL', 10)])[0]!.volume_l).toBeNull()
  })
})

describe('liveAlerts', () => {
  const NOW = Date.parse('2026-08-03T12:00:00Z')

  it('drops a low-fuel warning once a tanker has been', () => {
    // Tanks cross their reorder line every cycle. Alerting on each crossing lit
    // ten of twelve cards on the demo fleet — if everything is flagged, nothing
    // is. Only an UNRESOLVED low tank is an incident.
    const incidents = groupIncidents([ev('LOW_FUEL', 300), ev('REFILL', 200, 400)])
    expect(liveAlerts(incidents, NOW)).toHaveLength(0)
  })

  it('resolves a low-fuel warning refilled in the same tick', () => {
    // Crossing the threshold inside the delivery window emits LOW_FUEL then
    // REFILL at the same simulated instant. Reading that as unresolved put a
    // "Low fuel" banner over a tank at 89%.
    const incidents = groupIncidents([ev('LOW_FUEL', 200), ev('REFILL', 200, 400)])
    expect(liveAlerts(incidents, NOW)).toHaveLength(0)
  })

  it('keeps a low-fuel warning that has had no refill since', () => {
    const incidents = groupIncidents([ev('REFILL', 600, 400), ev('LOW_FUEL', 120)])
    const alerts = liveAlerts(incidents, NOW)
    expect(alerts).toHaveLength(1)
    expect(alerts[0]!.event_type).toBe('LOW_FUEL')
  })

  it('always keeps a drain — nothing resolves a theft', () => {
    const incidents = groupIncidents([ev('SUSPECTED_DRAIN', 300, -200), ev('REFILL', 100, 400)])
    expect(liveAlerts(incidents, NOW).map((i) => i.event_type)).toEqual(['SUSPECTED_DRAIN'])
  })

  it('forgets incidents older than the window', () => {
    const incidents = groupIncidents([ev('SUSPECTED_DRAIN', 60 * 40, -100)])
    expect(liveAlerts(incidents, NOW, 24)).toHaveLength(0)
  })

  it('scopes the refill check to the same generator', () => {
    // A refill on gen-2 must not clear gen-1's warning.
    const incidents = groupIncidents([
      ev('LOW_FUEL', 300, null, 'gen-1'),
      ev('REFILL', 100, 400, 'gen-2'),
    ])
    expect(liveAlerts(incidents, NOW).map((i) => i.generator_id)).toEqual(['gen-1'])
  })

  it('never alerts on refills or engine events', () => {
    const incidents = groupIncidents([ev('REFILL', 10, 300), ev('ENGINE_STOP', 5)])
    expect(liveAlerts(incidents, NOW)).toHaveLength(0)
  })

  it('clears a low-fuel warning once the pump has transferred', () => {
    // Under the two-tier model a day tank is replenished by TRANSFER, not by a
    // tanker. Resolving only on REFILL would leave every low-fuel alert lit
    // forever, since REFILL is no longer emitted for day tanks at all.
    const incidents = groupIncidents([ev('LOW_FUEL', 300), ev('TRANSFER', 200, 400)])
    expect(liveAlerts(incidents, NOW)).toHaveLength(0)
  })

  it('never alerts on a transfer — it is routine plumbing', () => {
    // ~800 transfers against ~50 deliveries in a 60-day backfill. Alerting on
    // these would bury every incident that matters.
    const incidents = groupIncidents([ev('TRANSFER', 10, 200)])
    expect(liveAlerts(incidents, NOW)).toHaveLength(0)
  })

  it('clears a sensor outage once the signal returns', () => {
    const incidents = groupIncidents([
      siteEv('SIGNAL_LOSS', 300),
      siteEv('SIGNAL_RESTORED', 200),
    ])
    expect(liveAlerts(incidents, NOW)).toHaveLength(0)
  })

  it('keeps a sensor outage that has not come back', () => {
    const incidents = groupIncidents([siteEv('SIGNAL_LOSS', 120)])
    expect(liveAlerts(incidents, NOW).map((i) => i.event_type)).toEqual(['SIGNAL_LOSS'])
  })

  it('scopes signal resolution to the same tank', () => {
    // Tank B coming back must not clear tank A's outage.
    const incidents = groupIncidents([
      siteEv('SIGNAL_LOSS', 300, null, 'tank-a'),
      siteEv('SIGNAL_RESTORED', 100, null, 'tank-b'),
    ])
    expect(liveAlerts(incidents, NOW).map((i) => i.tank_id)).toEqual(['tank-a'])
  })

  it('always keeps a short delivery — the invoice is already wrong', () => {
    const incidents = groupIncidents([
      siteEv('SHORT_DELIVERY', 300, -400),
      siteEv('DELIVERY', 100, 4000),
    ])
    expect(liveAlerts(incidents, NOW).map((i) => i.event_type)).toEqual(['SHORT_DELIVERY'])
  })

  it('always keeps an unverified loss', () => {
    const incidents = groupIncidents([siteEv('UNVERIFIED_LOSS', 200, -300)])
    expect(liveAlerts(incidents, NOW)).toHaveLength(1)
  })
})

describe('site-level incidents', () => {
  it('groups bulk events per tank rather than collapsing them', () => {
    // Every site-level event has a null generator. Grouping on generator_id
    // alone would merge two different tanks' outages into one incident.
    const incidents = groupIncidents([
      siteEv('SIGNAL_LOSS', 100, null, 'tank-a'),
      siteEv('SIGNAL_LOSS', 100, null, 'tank-b'),
    ])
    expect(incidents).toHaveLength(2)
    expect(incidents.map((i) => i.tank_id).sort()).toEqual(['tank-a', 'tank-b'])
  })

  it('still collapses a run on one tank', () => {
    const incidents = groupIncidents([
      siteEv('SUSPECTED_DRAIN', 30, -5),
      siteEv('SUSPECTED_DRAIN', 25, -5),
      siteEv('SUSPECTED_DRAIN', 20, -5),
    ])
    expect(incidents).toHaveLength(1)
    expect(incidents[0]!.count).toBe(3)
    expect(incidents[0]!.volume_l).toBe(-15)
    expect(incidents[0]!.generator_id).toBeNull()
  })

  it('carries the subject so a generator and a tank never collide', () => {
    const incidents = groupIncidents([ev('LOW_FUEL', 100), siteEv('SIGNAL_LOSS', 100)])
    expect(incidents.map((i) => i.subject).sort()).toEqual(['gen-1', 'tank-bulk-1'])
  })
})

describe('isAlerting', () => {
  it('alerts on drains and low fuel', () => {
    expect(isAlerting('SUSPECTED_DRAIN')).toBe(true)
    expect(isAlerting('LOW_FUEL')).toBe(true)
  })

  it('stays quiet for refills and engine transitions', () => {
    // A residential unit emits several engine events a day; alerting on them
    // would bury the ones that matter.
    expect(isAlerting('REFILL')).toBe(false)
    expect(isAlerting('ENGINE_START')).toBe(false)
    expect(isAlerting('ENGINE_STOP')).toBe(false)
  })
})
