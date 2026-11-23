/** Endpoint wrappers. Thin on purpose — the interesting logic lives in stores. */

import { get, post } from './client'
import type {
  Event,
  EventType,
  FleetSummary,
  Generator,
  GeneratorConsumption,
  GeneratorDetail,
  Page,
  Reading,
  SimulateResult,
  Site,
  SiteFuel,
  SiteSummary,
  TankConsumption,
  TankKind,
  TankSeries,
  TankState,
} from './types'

export const listSites = () => get<Site[]>('/sites')

/**
 * Every site rolled up to one row, in a single call — the query behind the map.
 *
 * Read `dark_sensors` alongside the reporting counts; see the note on
 * `SiteSummary`. A site with no bulk tank is still present here, with a zero
 * capacity and a null level.
 */
export const listSiteSummaries = () => get<SiteSummary[]>('/sites/summary')

export const listGenerators = (params: { site_id?: string; status?: string } = {}) =>
  get<Generator[]>('/generators', params)

export const getGenerator = (id: string) => get<GeneratorDetail>(`/generators/${id}`)

/**
 * One reading per generator, fleet-wide, in a single call.
 *
 * Returns a bare array, not a page. Ordered by generator_id, NOT by time.
 * Generators that have never produced a reading are simply absent.
 */
export const latestReadings = () => get<Reading[]>('/readings/latest')

export const getSummary = () => get<FleetSummary>('/summary')

// --- tanks: both storage tiers ---

/** BULK first then by name. Levels are measured or null — never estimated. */
export const listTanks = (params: { site_id?: string; generator_id?: string; kind?: TankKind } = {}) =>
  get<TankState[]>('/tanks', params)

/** One site's bulk reserve plus the day tanks it feeds. */
export const getSiteFuel = (siteId: string) => get<SiteFuel>(`/sites/${siteId}/fuel`)

/** Ascending by time. Buckets with no readings are ABSENT — break the line. */
export const getTankSeries = (tankId: string, hours = 24, bucket_minutes?: number) =>
  get<TankSeries>(`/tanks/${tankId}/series`, { hours, bucket_minutes })

/** Days ascending; days with no activity are absent. `samples` flags partial days. */
export const getTankConsumption = (tankId: string, days = 30) =>
  get<TankConsumption>(`/tanks/${tankId}/consumption`, { days })

export const getTank = (tankId: string) =>
  listTanks().then((tanks) => tanks.find((tank) => tank.id === tankId) ?? null)

/** Newest-first. Reverse before charting. */
export const getReadings = (
  id: string,
  params: { start?: string; end?: string; before?: string; limit?: number } = {},
) => get<Page<Reading>>(`/generators/${id}/readings`, params)

/** Days ascending, and days with no data are absent — gap-fill before plotting. */
export const getConsumption = (id: string, days = 30) =>
  get<GeneratorConsumption>(`/generators/${id}/consumption`, { days })

/**
 * Newest-first. `event_type` repeats per value.
 *
 * `site_id` matches on either route an event reaches a site by — through its
 * tank, or through its generator. Engine transitions carry a generator and no
 * tank; a delivery into shared bulk carries a tank and no generator. Filtering
 * server-side is what makes `next_cursor` meaningful: paginating a page you
 * then filter in the browser drops rows silently.
 */
export const listEvents = (
  params: {
    generator_id?: string
    tank_id?: string
    site_id?: string
    event_type?: EventType[]
    start?: string
    end?: string
    before?: string
    limit?: number
  } = {},
) => get<Page<Event>>('/events', params)

// --- simulation controls, for driving a demo ---

export const simulateDrain = (generator_id: string, volume_l?: number, steps?: number) =>
  post<SimulateResult>('/admin/simulate/drain', { generator_id, volume_l, steps })

export const simulateRefill = (generator_id: string, steps?: number) =>
  post<SimulateResult>('/admin/simulate/refill', { generator_id, steps })

export const simulateLevel = (
  generator_id: string,
  level: { level_l?: number; level_pct?: number },
  steps?: number,
) => post<SimulateResult>('/admin/simulate/level', { generator_id, ...level, steps })
