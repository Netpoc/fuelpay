/**
 * Recent incidents, indexed by generator.
 *
 * The dashboard needs "does this unit have a live problem" for every card, so
 * events are fetched once fleet-wide and grouped rather than per-card.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { listEvents } from '@/api/fleet'
import type { Event, EventType } from '@/api/types'
import { groupIncidents, liveAlerts, worstFirst, type Incident } from '@/lib/incidents'

/**
 * How long an incident keeps flagging its generator on the dashboard.
 *
 * Long enough to survive an overnight theft going unnoticed until morning;
 * short enough that a card is not still shouting about last week.
 */
export const ALERT_WINDOW_HOURS = 24

export const useIncidentsStore = defineStore('incidents', () => {
  const events = ref<Event[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  /** Incidents acknowledged by the operator, by incident id. */
  const dismissed = ref(new Set<string>())

  const incidents = computed(() => groupIncidents(events.value))

  const alerting = computed(() =>
    liveAlerts(incidents.value, Date.now(), ALERT_WINDOW_HOURS).filter(
      (incident) => !dismissed.value.has(incident.id),
    ),
  )

  /** generator id -> its live alerts, worst first. */
  const alertsByGenerator = computed(() => {
    const map = new Map<string, Incident[]>()
    for (const incident of alerting.value) {
      if (!incident.generator_id) continue
      const list = map.get(incident.generator_id) ?? []
      list.push(incident)
      map.set(incident.generator_id, list)
    }
    for (const list of map.values()) list.sort(worstFirst)
    return map
  })

  /**
   * tank id -> its live alerts, worst first.
   *
   * Bulk-storage incidents — a short delivery, a dark bulk sensor — carry no
   * generator, so they are absent from `alertsByGenerator` by construction.
   * Without this index they would be alerting and invisible, which is the
   * worst of both.
   */
  const alertsByTank = computed(() => {
    const map = new Map<string, Incident[]>()
    for (const incident of alerting.value) {
      if (!incident.tank_id) continue
      const list = map.get(incident.tank_id) ?? []
      list.push(incident)
      map.set(incident.tank_id, list)
    }
    for (const list of map.values()) list.sort(worstFirst)
    return map
  })

  /** Live alerts belonging to the site tier rather than to any generator. */
  const siteLevelAlerts = computed(() =>
    [...alerting.value].filter((incident) => !incident.generator_id).sort(worstFirst),
  )

  const alertCount = computed(() => alerting.value.length)

  /** Incidents for one generator, whatever their age — for the detail page. */
  const forGenerator = (id: string) =>
    incidents.value.filter((incident) => incident.generator_id === id)

  /** Incidents for one tank, whatever their age. */
  const forTank = (id: string) => incidents.value.filter((incident) => incident.tank_id === id)

  async function load(hours = ALERT_WINDOW_HOURS * 3, types?: EventType[]) {
    loading.value = true
    error.value = null
    try {
      const since = new Date(Date.now() - hours * 3_600_000).toISOString()
      const page = await listEvents({
        start: since,
        // TRANSFER and SIGNAL_RESTORED look like noise but are load-bearing:
        // they are what RESOLVED_BY uses to clear a LOW_FUEL or SIGNAL_LOSS
        // alert. Omitting them would leave every such alert lit forever, which
        // is the exact failure `liveAlerts` exists to prevent. They stay at
        // `debug` severity so they never raise an alert themselves.
        event_type:
          types ??
          [
            'SUSPECTED_DRAIN',
            'SHORT_DELIVERY',
            'UNVERIFIED_LOSS',
            'LOW_FUEL',
            'SIGNAL_LOSS',
            'SIGNAL_RESTORED',
            'DELIVERY',
            'TRANSFER',
            'REFILL',
          ],
        limit: 2000,
      })
      events.value = page.items
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : 'Could not load incidents.'
    } finally {
      loading.value = false
    }
  }

  function dismiss(id: string) {
    dismissed.value = new Set(dismissed.value).add(id)
  }

  function dismissForGenerator(generatorId: string) {
    const next = new Set(dismissed.value)
    for (const incident of alertsByGenerator.value.get(generatorId) ?? []) next.add(incident.id)
    dismissed.value = next
  }

  return {
    events,
    loading,
    error,
    incidents,
    alerting,
    alertsByGenerator,
    alertsByTank,
    siteLevelAlerts,
    alertCount,
    forGenerator,
    forTank,
    load,
    dismiss,
    dismissForGenerator,
  }
})
