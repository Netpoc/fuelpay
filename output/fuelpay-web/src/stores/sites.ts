/**
 * Sites as the map needs them: one row per site, always.
 *
 * A third store rather than a computed on `fleet`, for three reasons.
 *
 * 1. `fleet.bulkBySite` cannot back a map and must not be changed to. It skips
 *    any site with no BULK tank, and widening it would regress its two existing
 *    consumers — `bulkNeedsDelivery` would start ranking zero-capacity sites,
 *    and the dashboard's bulk grid would render a card reading "— of 0 L".
 * 2. `/sites/summary` is a rollup with its own cadence, and the obvious place to
 *    hang the live stream off when it lands.
 * 3. The per-site alert index needs `incidents` AND `fleet` together. Putting it
 *    in either makes that store depend on the other; a third store that reads
 *    both is the only arrangement without a cycle.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { listSiteSummaries } from '@/api/fleet'
import type { Site, SiteSummary, TankState as TankRow } from '@/api/types'
import { tankState, type TankState } from '@/components/tank/state'
import { worstFirst, type Incident } from '@/lib/incidents'
import { useFleetStore, type FleetRow, type SiteBulk } from './fleet'
import { useIncidentsStore } from './incidents'

/** Worst first. Mirrors the rank used for the bulk grid on the dashboard. */
const STATE_RANK: Record<TankState, number> = { critical: 0, low: 1, watch: 2, ok: 3 }

export interface SiteMapRow {
  site: Site
  /** Null until `/sites/summary` has loaded, or if it failed. */
  summary: SiteSummary | null
  /** From the fleet store. Absent for a site with no bulk tank. */
  bulk: SiteBulk | undefined
  dayTanks: TankRow[]
  generators: FleetRow[]
  running: number
  /**
   * Worst state across both tiers, or undefined when nothing is measurable.
   * Undefined is not "fine" — it means there is no level to classify.
   */
  state: TankState | undefined
  /** Sensors currently quiet, either tier. Makes every figure here provisional. */
  darkSensors: number
  /** True when a tier's total was summed over only some of its tanks. */
  partial: boolean
  alerts: Incident[]
}

/**
 * Worst state across a site's two tiers.
 *
 * A tier with no measurable level contributes nothing rather than an optimistic
 * "ok" — an unmeasured tank has no state, and defaulting it to healthy is the
 * failure this product exists to prevent.
 */
export function siteState(summary: SiteSummary | null, bulk: SiteBulk | undefined) {
  const states: TankState[] = []

  if (summary) {
    if (summary.bulk_tanks_total && summary.bulk_level_pct !== null) {
      states.push(tankState(summary.bulk_level_pct, summary.bulk_reorder_threshold_pct))
    }
    if (summary.day_tanks_total && summary.day_level_pct !== null) {
      states.push(tankState(summary.day_level_pct, summary.day_reorder_threshold_pct))
    }
  } else if (bulk?.levelPct !== undefined) {
    // Fallback while the rollup is still in flight, so pins render immediately.
    states.push(bulk.state)
  }

  return states.sort((a, b) => STATE_RANK[a] - STATE_RANK[b])[0]
}

export const useSitesStore = defineStore('sites', () => {
  const fleet = useFleetStore()
  const incidents = useIncidentsStore()

  const summaries = ref(new Map<string, SiteSummary>())
  const loading = ref(false)
  const error = ref<string | null>(null)
  const loadedAt = ref<number | null>(null)
  /** The pin the map is focused on. Null when nothing is selected. */
  const selectedId = ref<string | null>(null)

  /**
   * site id -> live alerts, worst first.
   *
   * The site-tier index the app lacked. An incident reaches a site through its
   * tank or through its generator: a delivery into shared bulk carries no
   * generator, an engine transition carries no tank. Resolving only one way
   * would drop half a site's problems off its pin.
   *
   * Derived from `incidents.alerting` rather than recomputed, so the subtle
   * part — what counts as *live*, which needs RESOLVED_BY — has one home.
   */
  const alertsBySite = computed(() => {
    const siteOfTank = new Map(fleet.tanks.map((tank) => [tank.id, tank.site_id]))
    const siteOfGenerator = new Map(
      [...fleet.generators.values()].map((generator) => [generator.id, generator.site_id]),
    )

    const map = new Map<string, Incident[]>()
    for (const incident of incidents.alerting) {
      const siteId =
        (incident.tank_id ? siteOfTank.get(incident.tank_id) : undefined) ??
        (incident.generator_id ? siteOfGenerator.get(incident.generator_id) : undefined)
      if (!siteId) continue
      const list = map.get(siteId) ?? []
      list.push(incident)
      map.set(siteId, list)
    }
    for (const list of map.values()) list.sort(worstFirst)
    return map
  })

  /**
   * One row per site, always — including a site with no bulk tank, which is
   * exactly the case `fleet.bulkBySite` drops.
   *
   * Falls back to fleet data when the rollup has not arrived, so the map draws
   * pins in the right places on first paint instead of waiting on a sixth call.
   */
  const rows = computed<SiteMapRow[]>(() =>
    fleet.siteList.map((site) => {
      const summary = summaries.value.get(site.id) ?? null
      const bulk = fleet.bulkBySite.get(site.id)
      const generators = fleet.rows.filter((row) => row.generator.site_id === site.id)
      const dayTanks = fleet.tanks.filter(
        (tank) => tank.kind === 'DAY' && tank.site_id === site.id,
      )

      const partial = summary
        ? (summary.bulk_tanks_reporting < summary.bulk_tanks_total ||
            summary.day_tanks_reporting < summary.day_tanks_total)
        : (bulk?.partial ?? false)

      return {
        site,
        summary,
        bulk,
        dayTanks,
        generators,
        running: summary?.running_count ?? generators.filter((row) => row.running).length,
        state: siteState(summary, bulk),
        darkSensors:
          summary?.dark_sensors ??
          fleet.tanks.filter(
            (tank) => tank.site_id === site.id && tank.sensor_status === 'OFFLINE',
          ).length,
        partial,
        alerts: alertsBySite.value.get(site.id) ?? [],
      }
    }),
  )

  const byId = computed(() => new Map(rows.value.map((row) => [row.site.id, row])))

  /** Worst first, then emptiest — the order the rail lists them in. */
  const needsAttention = computed(() =>
    [...rows.value]
      .filter((row) => row.alerts.length || row.darkSensors || row.state === 'low' || row.state === 'critical')
      .sort(
        (a, b) =>
          (b.alerts.length ? 1 : 0) - (a.alerts.length ? 1 : 0) ||
          STATE_RANK[a.state ?? 'ok'] - STATE_RANK[b.state ?? 'ok'],
      ),
  )

  const selected = computed(() =>
    selectedId.value ? (byId.value.get(selectedId.value) ?? null) : null,
  )

  async function load() {
    loading.value = true
    error.value = null
    try {
      const rollups = await listSiteSummaries()
      summaries.value = new Map(rollups.map((row) => [row.site.id, row]))
      loadedAt.value = Date.now()
    } catch (caught) {
      // Not fatal: `rows` falls back to fleet data, so the map still draws.
      // Only the usage figures are missing.
      error.value = caught instanceof Error ? caught.message : 'Could not load site rollups.'
    } finally {
      loading.value = false
    }
  }

  function select(siteId: string | null) {
    selectedId.value = siteId
  }

  return {
    summaries,
    loading,
    error,
    loadedAt,
    selectedId,
    rows,
    byId,
    needsAttention,
    selected,
    alertsBySite,
    load,
    select,
  }
})
