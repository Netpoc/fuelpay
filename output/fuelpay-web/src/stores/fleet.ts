/**
 * The fleet as the UI needs it: generators joined to their site and their
 * newest reading, with the derived state every screen asks for.
 *
 * The join happens here rather than per-component because the API deliberately
 * keeps these separate — `/generators` and `/readings/latest` are two cheap
 * calls, versus twelve round-trips to `/generators/{id}`.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { getSummary, latestReadings, listGenerators, listSites, listTanks } from '@/api/fleet'
import type {
  FleetSummary,
  Generator,
  Reading,
  Site,
  TankState as TankRow,
} from '@/api/types'
import { tankState, type TankState } from '@/components/tank/state'

export interface FleetRow {
  generator: Generator
  site: Site | undefined
  reading: Reading | undefined
  /** Percent full, straight from the API. Undefined when there is no reading yet. */
  fuelPct: number | undefined
  belowThreshold: boolean
  state: TankState
  running: boolean
  /** The generator's instrumented day tank, for sensor status. */
  dayTank: TankRow | undefined
}

/** A site's bulk reserve, rolled up from its tanks. */
export interface SiteBulk {
  site: Site
  tanks: TankRow[]
  capacityL: number
  /** Summed over REPORTING tanks only. Undefined when none are reporting. */
  levelL: number | undefined
  levelPct: number | undefined
  reporting: number
  total: number
  /** True when some — but not all — of the site's bulk sensors are dark. */
  partial: boolean
  state: TankState
}

export const useFleetStore = defineStore('fleet', () => {
  const sites = ref(new Map<string, Site>())
  const generators = ref(new Map<string, Generator>())
  const latest = ref(new Map<string, Reading>())
  const summary = ref<FleetSummary | null>(null)
  const tanks = ref<TankRow[]>([])

  const loading = ref(false)
  const error = ref<string | null>(null)
  const loadedAt = ref<number | null>(null)

  const dayTankByGenerator = computed(
    () =>
      new Map(
        tanks.value
          .filter((tank) => tank.kind === 'DAY' && tank.generator_id)
          .map((tank) => [tank.generator_id as string, tank]),
      ),
  )

  const rows = computed<FleetRow[]>(() =>
    [...generators.value.values()]
      .sort((a, b) => a.serial.localeCompare(b.serial))
      .map((generator) => {
        const reading = latest.value.get(generator.id)
        // Take fuel_level_pct as given. Recomputing it from litres over
        // capacity would quietly discard the sensor noise and quantisation the
        // simulator models on purpose, showing a cleaner tank than the probe
        // actually reports.
        const fuelPct = reading?.fuel_level_pct
        return {
          generator,
          site: sites.value.get(generator.site_id),
          reading,
          fuelPct,
          belowThreshold: fuelPct !== undefined && fuelPct < generator.reorder_threshold_pct,
          state: tankState(fuelPct ?? 100, generator.reorder_threshold_pct),
          running: reading?.engine_running ?? false,
          dayTank: dayTankByGenerator.value.get(generator.id),
        }
      }),
  )

  /**
   * Bulk storage per site.
   *
   * Totals are summed over reporting tanks only, and `partial` says when that
   * was a subset. A site with one dark sensor of two would otherwise appear to
   * be holding half the fuel it has, which reads as an emergency.
   */
  const bulkBySite = computed<Map<string, SiteBulk>>(() => {
    const map = new Map<string, SiteBulk>()
    for (const site of sites.value.values()) {
      const siteTanks = tanks.value.filter(
        (tank) => tank.kind === 'BULK' && tank.site_id === site.id,
      )
      if (!siteTanks.length) continue

      const reporting = siteTanks.filter((tank) => tank.level_l !== null)
      const capacityL = siteTanks.reduce((sum, tank) => sum + tank.capacity_l, 0)
      const levelL = reporting.length
        ? reporting.reduce((sum, tank) => sum + (tank.level_l ?? 0), 0)
        : undefined
      const levelPct = levelL !== undefined && capacityL ? (levelL / capacityL) * 100 : undefined

      // Threshold comes from the tanks themselves; they share one in the seed,
      // and taking the strictest is the safe read when they differ.
      const threshold = Math.max(...siteTanks.map((tank) => tank.reorder_threshold_pct))

      map.set(site.id, {
        site,
        tanks: siteTanks,
        capacityL,
        levelL,
        levelPct,
        reporting: reporting.length,
        total: siteTanks.length,
        partial: reporting.length > 0 && reporting.length < siteTanks.length,
        state: tankState(levelPct ?? 100, threshold),
      })
    }
    return map
  })

  /**
   * Sites whose bulk reserve is at or below its reorder line, emptiest first.
   *
   * Sites with a dark bulk sensor are excluded rather than included. Their
   * total is summed over a subset, so it reads low whether or not they are —
   * dispatching a tanker on that would be acting on a measurement nobody took.
   * They surface through `darkSensors` instead, which is the actual problem.
   */
  const bulkNeedsDelivery = computed(() =>
    [...bulkBySite.value.values()]
      .filter((bulk) => !bulk.partial && bulk.levelL !== undefined)
      .filter((bulk) => bulk.state === 'low' || bulk.state === 'critical')
      .sort((a, b) => (a.levelPct ?? 100) - (b.levelPct ?? 100)),
  )

  /** Every tank whose sensor is not currently reporting, either tier. */
  const darkSensors = computed(() =>
    tanks.value.filter((tank) => tank.sensor_status === 'OFFLINE'),
  )

  const byId = computed(() => new Map(rows.value.map((row) => [row.generator.id, row])))

  const needsAttention = computed(() =>
    rows.value
      .filter((row) => row.state === 'low' || row.state === 'critical')
      .sort((a, b) => (a.fuelPct ?? 100) - (b.fuelPct ?? 100)),
  )

  const siteList = computed(() =>
    [...sites.value.values()].sort((a, b) => a.name.localeCompare(b.name)),
  )

  async function loadAll() {
    loading.value = true
    error.value = null
    try {
      const [siteRows, generatorRows, readingRows, summaryRow, tankRows] = await Promise.all([
        listSites(),
        listGenerators(),
        latestReadings(),
        getSummary(),
        listTanks(),
      ])
      sites.value = new Map(siteRows.map((site) => [site.id, site]))
      generators.value = new Map(generatorRows.map((generator) => [generator.id, generator]))
      latest.value = new Map(readingRows.map((reading) => [reading.generator_id, reading]))
      summary.value = summaryRow
      tanks.value = tankRows
      loadedAt.value = Date.now()
    } catch (caught) {
      error.value = caught instanceof Error ? caught.message : 'Failed to load the fleet.'
    } finally {
      loading.value = false
    }
  }

  /**
   * Merge newer readings in.
   *
   * Older-or-equal timestamps are dropped rather than applied: the stream
   * delivers at-least-once, so a reconnect replays rows we already hold, and
   * applying them would make a tank visibly jump backwards.
   */
  function applyReadings(incoming: Reading[]) {
    const next = new Map(latest.value)
    for (const reading of incoming) {
      const held = next.get(reading.generator_id)
      if (held && held.time >= reading.time) continue
      next.set(reading.generator_id, reading)
    }
    latest.value = next
  }

  function applySummary(next: FleetSummary) {
    summary.value = next
  }

  return {
    sites,
    generators,
    latest,
    summary,
    tanks,
    loading,
    error,
    loadedAt,
    rows,
    byId,
    needsAttention,
    siteList,
    bulkBySite,
    bulkNeedsDelivery,
    darkSensors,
    loadAll,
    applyReadings,
    applySummary,
  }
})
