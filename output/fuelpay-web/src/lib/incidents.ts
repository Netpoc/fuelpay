/**
 * What each event type means to an operator.
 *
 * One table, consumed by the chart markers, the dashboard alert badges and the
 * feed — so a drain cannot be red in one place and amber in another.
 */

import type { Event, EventType } from '@/api/types'
import type { StatusKey } from '@/theme/tokens'

export type Severity = 'critical' | 'warning' | 'info' | 'debug'

interface Spec {
  severity: Severity
  label: string
  /** Shown on charts and badges. Direction carries meaning: fuel in vs fuel out. */
  glyph: string
  /**
   * Which status colour to paint this with. A key rather than a hex, because
   * the actual value now depends on the active theme.
   */
  status: StatusKey
}

export const EVENT_SPEC: Record<EventType, Spec> = {
  SUSPECTED_DRAIN: {
    severity: 'critical',
    label: 'Suspected drain',
    glyph: '▼',
    status: 'critical',
  },
  // Billed for more fuel than was delivered. The reason a bulk tank is
  // instrumented at all, so it ranks with theft rather than below it.
  SHORT_DELIVERY: {
    severity: 'critical',
    label: 'Short delivery',
    glyph: '▼',
    status: 'critical',
  },
  // Fuel missing across a sensor outage. Critical, but deliberately distinct
  // from a drain: nobody was watching, so it cannot be called theft.
  UNVERIFIED_LOSS: {
    severity: 'critical',
    label: 'Unverified loss',
    glyph: '?',
    status: 'critical',
  },
  LOW_FUEL: {
    severity: 'warning',
    label: 'Low fuel',
    glyph: '!',
    status: 'watch',
  },
  // A tank nobody can see. Not a fuel problem yet, but it is the condition
  // under which a fuel problem would go unnoticed.
  SIGNAL_LOSS: {
    severity: 'warning',
    label: 'Sensor offline',
    glyph: '⚠',
    status: 'watch',
  },
  DELIVERY: {
    severity: 'info',
    label: 'Delivery',
    glyph: '▲',
    status: 'ok',
  },
  REFILL: {
    severity: 'info',
    label: 'Refill',
    glyph: '▲',
    status: 'ok',
  },
  // Routine plumbing, and by far the highest-volume event in the system —
  // ~800 in a 60-day backfill against ~50 deliveries. Debug, or the feed
  // becomes a list of pump cycles with the fraud buried inside it.
  TRANSFER: { severity: 'debug', label: 'Transfer to day tank', glyph: '', status: 'ok' },
  SIGNAL_RESTORED: { severity: 'debug', label: 'Sensor back online', glyph: '', status: 'ok' },
  // Engine transitions are high-volume — a residential unit emits several a
  // day. They belong in the feed and drive the tank's wave state, but they
  // never raise an alert or they would drown the ones that matter.
  ENGINE_START: { severity: 'debug', label: 'Engine start', glyph: '', status: 'ok' },
  ENGINE_STOP: { severity: 'debug', label: 'Engine stop', glyph: '', status: 'ok' },
  // Tractors. Return-line diversion and quota breaches both burn fuel the job
  // did not need; the detail says which.
  OVERCONSUMPTION: {
    severity: 'critical',
    label: 'Over-consumption',
    glyph: '▼',
    status: 'critical',
  },
  // Refuel billed for more than the tank sensor saw arrive.
  SHORT_FILL: { severity: 'critical', label: 'Short fill', glyph: '▼', status: 'critical' },
  MISUSE: { severity: 'warning', label: 'Misuse', glyph: '!', status: 'watch' },
  FIELD_ENTER: { severity: 'debug', label: 'Entered field', glyph: '', status: 'ok' },
  FIELD_EXIT: { severity: 'debug', label: 'Left field', glyph: '', status: 'ok' },
}

export const isAlerting = (type: EventType) => {
  const severity = EVENT_SPEC[type].severity
  return severity === 'critical' || severity === 'warning'
}

/** Types worth drawing on a fuel-level chart: the ones that move the level. */
export const CHART_EVENT_TYPES: EventType[] = [
  'SUSPECTED_DRAIN',
  'SHORT_DELIVERY',
  'UNVERIFIED_LOSS',
  'LOW_FUEL',
  // TRANSFER is what actually refills a day tank now, so omitting it would
  // leave every step up in a generator's chart unexplained.
  'TRANSFER',
  'DELIVERY',
  'REFILL',
]

/**
 * What belongs in a human-facing activity feed.
 *
 * ENGINE_START/ENGINE_STOP and TRANSFER are deliberately absent. They are the
 * highest-volume rows in the system by an order of magnitude — a 24/7 bank
 * branch emits engine transitions all day and a day tank is topped up
 * constantly — and including them buries the one delivery and the one dark
 * sensor that a site's operator actually needs to see. Same reason they sit at
 * `debug` severity in EVENT_SPEC.
 *
 * They are still available: a feed offering this list should also offer an
 * unfiltered view rather than pretending the rows do not exist.
 */
export const FEED_EVENT_TYPES: EventType[] = [
  'SUSPECTED_DRAIN',
  'SHORT_DELIVERY',
  'UNVERIFIED_LOSS',
  'LOW_FUEL',
  'SIGNAL_LOSS',
  'SIGNAL_RESTORED',
  'DELIVERY',
  'REFILL',
]

/**
 * Which way an event moved the fuel.
 *
 * Charts previously inferred this as "drain, or else a refill", which was safe
 * when the only loss was theft. It is not any more: a SHORT_DELIVERY or an
 * UNVERIFIED_LOSS would fall through to the refill branch and be drawn as a
 * green arrow up — a loss rendered as a gain, which is the single most
 * misleading thing this chart could do.
 */
const FUEL_OUT: EventType[] = [
  'SUSPECTED_DRAIN',
  'SHORT_DELIVERY',
  'UNVERIFIED_LOSS',
  'SHORT_FILL',
  'OVERCONSUMPTION',
]

export const isFuelLoss = (type: EventType) => FUEL_OUT.includes(type)

/**
 * What clears each alerting condition.
 *
 * Without this a tank that crossed its reorder line at 02:00 keeps shouting
 * after the pump has refilled it, and every dark sensor stays flagged forever
 * once it comes back. Both make the dashboard noise.
 */
const RESOLVED_BY: Partial<Record<EventType, EventType[]>> = {
  // A day tank is replenished by TRANSFER now; DELIVERY and the legacy REFILL
  // are kept so pre-two-tier history still resolves.
  LOW_FUEL: ['TRANSFER', 'DELIVERY', 'REFILL'],
  SIGNAL_LOSS: ['SIGNAL_RESTORED'],
}

/**
 * Who an event is about.
 *
 * Site-level events — a tanker delivery into shared bulk, a bulk sensor going
 * dark — carry no generator, so grouping on `generator_id` alone would collapse
 * every one of them into a single null-keyed bucket.
 */
export const subjectOf = (event: {
  generator_id: string | null
  tank_id: string | null
  vehicle_id?: string | null
}) => event.generator_id ?? event.tank_id ?? event.vehicle_id ?? 'unknown'

/**
 * Collapse a siphon's event series into one incident.
 *
 * A theft emits one SUSPECTED_DRAIN per tick as the pump works, so a 30-minute
 * siphon can be six rows. Six identical markers stacked on a chart, or six
 * badges on a card, misrepresent one incident as six — group anything of the
 * same type on the same generator within `gapMinutes` of the last one.
 */
export interface Incident {
  id: string
  /** Null for site-level incidents: bulk storage belongs to no one generator. */
  generator_id: string | null
  tank_id: string | null
  /** `generator_id ?? tank_id` — what the run is grouped and resolved on. */
  subject: string
  event_type: EventType
  /** When the run started. */
  occurred_at: string
  /** When it finished — equal to `occurred_at` for a single-event incident. */
  ended_at: string
  /** Signed total across the run. */
  volume_l: number | null
  fuel_level_l: number | null
  count: number
  detail: Record<string, unknown>
}

export function groupIncidents(events: Event[], gapMinutes = 30): Incident[] {
  // Oldest first makes the run-detection a single forward pass.
  const ordered = [...events].sort((a, b) => a.occurred_at.localeCompare(b.occurred_at))
  const out: Incident[] = []

  for (const event of ordered) {
    const subject = subjectOf(event)
    const open = out.find(
      (incident) =>
        incident.subject === subject &&
        incident.event_type === event.event_type &&
        new Date(event.occurred_at).getTime() - new Date(incident.ended_at).getTime() <=
          gapMinutes * 60_000,
    )

    if (open) {
      open.ended_at = event.occurred_at
      open.count += 1
      if (event.volume_l !== null) open.volume_l = (open.volume_l ?? 0) + event.volume_l
      open.fuel_level_l = event.fuel_level_l
      open.detail = event.detail
      continue
    }

    out.push({
      id: event.id,
      generator_id: event.generator_id,
      tank_id: event.tank_id,
      subject,
      event_type: event.event_type,
      occurred_at: event.occurred_at,
      ended_at: event.occurred_at,
      volume_l: event.volume_l,
      fuel_level_l: event.fuel_level_l,
      count: 1,
      detail: event.detail,
    })
  }

  return out.sort((a, b) => b.occurred_at.localeCompare(a.occurred_at))
}

/**
 * The incidents actually worth shouting about right now.
 *
 * A LOW_FUEL event is not by itself a problem: tanks cross their reorder
 * threshold on the way down every single cycle, and a tanker turns up. Treating
 * each crossing as an alert lit ten of twelve cards on the demo fleet, which
 * makes the dashboard useless — if everything is flagged, nothing is.
 *
 * So low fuel only alerts while it is *unresolved*: nothing has replenished
 * that tank since. A sensor outage clears the same way, when the signal comes
 * back. A suspected drain always alerts, because nothing resolves a theft.
 */
/**
 * Severity order within one subject, worst first.
 *
 * Lives here rather than in a store because both the incidents store and the
 * per-site index order by it, and two copies would eventually disagree about
 * which of a site's problems is the one to show on a pin.
 */
const INCIDENT_RANK: Partial<Record<EventType, number>> = {
  SUSPECTED_DRAIN: 0,
  SHORT_DELIVERY: 0,
  UNVERIFIED_LOSS: 1,
  LOW_FUEL: 2,
  SIGNAL_LOSS: 3,
}

export const worstFirst = (a: Incident, b: Incident) =>
  (INCIDENT_RANK[a.event_type] ?? 9) - (INCIDENT_RANK[b.event_type] ?? 9)

export function liveAlerts(
  incidents: Incident[],
  now: number = Date.now(),
  windowHours = 24,
): Incident[] {
  const cutoff = now - windowHours * 3_600_000

  // subject -> event type -> when that type last occurred on it.
  const lastBySubject = new Map<string, Map<EventType, number>>()
  for (const incident of incidents) {
    const perType = lastBySubject.get(incident.subject) ?? new Map<EventType, number>()
    const at = new Date(incident.ended_at).getTime()
    perType.set(incident.event_type, Math.max(perType.get(incident.event_type) ?? 0, at))
    lastBySubject.set(incident.subject, perType)
  }

  return incidents.filter((incident) => {
    if (!isAlerting(incident.event_type)) return false
    const ended = new Date(incident.ended_at).getTime()
    if (ended < cutoff) return false

    const resolvers = RESOLVED_BY[incident.event_type]
    if (!resolvers) return true

    const perType = lastBySubject.get(incident.subject)
    const resolvedAt = Math.max(0, ...resolvers.map((type) => perType?.get(type) ?? 0))
    // Strictly before. When a tank crosses its threshold and the pump responds
    // in the same tick, LOW_FUEL and TRANSFER share a timestamp — treating that
    // as unresolved left cards reading "Low fuel" over a tank sitting at 89%.
    return resolvedAt < ended
  })
}
