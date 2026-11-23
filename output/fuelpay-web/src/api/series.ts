import { get } from './client'

export interface SeriesPoint {
  time: string
  fuel_level_l: number
  /** The bucket's low. Preserves a siphon that averaging would erase. */
  fuel_min_l: number
  fuel_max_l: number
  load_kw: number
  consumed_l: number
  engine_running: boolean
  samples: number
}

export interface GeneratorSeries {
  generator_id: string
  bucket_minutes: number
  start: string
  end: string
  /** Ascending by time — chart-ready, unlike the paginated readings endpoint. */
  points: SeriesPoint[]
}

/**
 * Downsampled history for charting.
 *
 * Ask for a time span, not a resolution: the server picks a bucket that keeps
 * the response drawable, so a 60-day window is a few hundred points rather
 * than the 17,280 raw readings behind it.
 */
export const getSeries = (generatorId: string, hours: number) =>
  get<GeneratorSeries>(`/generators/${generatorId}/series`, { hours })
