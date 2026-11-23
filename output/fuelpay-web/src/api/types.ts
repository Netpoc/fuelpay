/**
 * Wire types, mirroring app/schemas.py in the service.
 *
 * Hand-written rather than generated: the file is small, and the comments
 * below record API behaviour the shapes alone do not convey — which endpoints
 * sort which way, when a field is null and why. Those are the things that
 * actually cause bugs here.
 *
 * `npm run gen:types` regenerates a machine copy from /openapi.json if you
 * want to diff against this.
 */

export type SiteProfile = 'TELECOM_TOWER' | 'OFFICE' | 'RESIDENTIAL' | 'BANK_BRANCH'
export type GeneratorStatus = 'ACTIVE' | 'MAINTENANCE' | 'DECOMMISSIONED'

/** Which tier of the fuel path a tank sits in. */
export type TankKind = 'BULK' | 'DAY'

/**
 * Whether a tank's sensor is reporting. Never "absent": a tank exists in
 * FuelPay because a sensor is in it, so silence is a fault, not missing
 * hardware.
 */
export type SensorStatus = 'ONLINE' | 'STALE' | 'OFFLINE'

export type EventType =
  | 'REFILL'
  | 'SUSPECTED_DRAIN'
  | 'LOW_FUEL'
  | 'ENGINE_START'
  | 'ENGINE_STOP'
  // Two-tier fuel path: tanker -> bulk -> day tank -> engine.
  | 'DELIVERY'
  | 'TRANSFER'
  | 'SHORT_DELIVERY'
  // Sensor connectivity.
  | 'SIGNAL_LOSS'
  | 'SIGNAL_RESTORED'
  | 'UNVERIFIED_LOSS'
  // Mobile machinery (tractors).
  | 'OVERCONSUMPTION'
  | 'SHORT_FILL'
  | 'MISUSE'
  | 'FIELD_ENTER'
  | 'FIELD_EXIT'

export interface Site {
  id: string
  name: string
  profile: SiteProfile
  latitude: number
  longitude: number
  address: string | null
}

export interface Generator {
  id: string
  site_id: string
  name: string
  serial: string
  kva_rating: number
  power_factor: number
  tank_capacity_l: number
  /** Percent of capacity. Per-generator, not a fleet constant — 20/25/30 in the seed. */
  reorder_threshold_pct: number
  status: GeneratorStatus
  commissioned_at: string | null
}

export interface Reading {
  generator_id: string
  /** ISO-8601 UTC. May be slightly in the FUTURE — see notes in lib/format.ts. */
  time: string
  /** Reported level: carries sensor noise and 0.1 L quantisation. Not the true level. */
  fuel_level_l: number
  /** Use this rather than dividing litres by capacity — see stores/fleet.ts. */
  fuel_level_pct: number
  load_kw: number
  /** 0 when the engine is off. */
  load_pct: number
  engine_running: boolean
  /** Litres burned since the previous reading — a per-interval delta, not cumulative. */
  consumed_l: number
  runtime_minutes: number
  latitude: number
  longitude: number
}

export interface Tank {
  id: string
  site_id: string
  /** Set for DAY tanks. Null for BULK, which serves the whole site. */
  generator_id: string | null
  name: string
  kind: TankKind
  capacity_l: number
  reorder_threshold_pct: number
  sensor_model: string
  sensor_serial: string
  calibrated_at: string
  last_seen_at: string | null
}

export interface TankState extends Tank {
  sensor_status: SensorStatus
  /**
   * Latest MEASURED level. Null when the sensor has never reported.
   *
   * Never an estimate. There is no fallback value to fall back to — an
   * unobserved tank has no level, and rendering a stale number as current is
   * the failure this product exists to prevent. Show the sensor status
   * instead.
   */
  level_l: number | null
  level_pct: number | null
  measured_at: string | null
  stale_seconds: number | null
}

export interface TankSeriesPoint {
  time: string
  level_l: number
  /** Lowest in the bucket. Preserves a siphon a mean would average away. */
  level_min_l: number
  level_max_l: number
  consumed_l: number
  transferred_l: number
  samples: number
}

export interface TankSeries {
  tank_id: string
  kind: TankKind
  capacity_l: number
  bucket_minutes: number
  start: string
  end: string
  /**
   * ASCENDING by time. Buckets with no readings are ABSENT, not zero-filled —
   * a gap means the sensor was dark. Break the line across one; joining two
   * levels either side draws straight through the window in which fuel is
   * most likely to have been taken.
   */
  points: TankSeriesPoint[]
}

export interface DailyTankFlow {
  /** UTC midnight of the bucket, as a full datetime. */
  day: string
  /** Burned by the engine. Always 0 for bulk, which feeds no engine. */
  consumed_l: number
  /** Out to a day tank (bulk), or in from bulk (day). */
  transferred_l: number
  delivered_l: number
  /** Positive magnitude, though events store losses negative. */
  drained_l: number
  /** Unaccounted across a sensor outage. NOT established theft — keep it apart. */
  unverified_loss_l: number
  /** Readings behind the row. Low means the day is partly unobserved, so the
   *  totals are a floor rather than the truth. */
  samples: number
}

export interface TankConsumption {
  tank_id: string
  tank_name: string
  kind: TankKind
  capacity_l: number
  /** ASCENDING by day. Days with no activity are absent — gap-fill before plotting. */
  days: DailyTankFlow[]
  total_consumed_l: number
  total_transferred_l: number
  total_delivered_l: number
  total_drained_l: number
  total_unverified_loss_l: number
}

export interface SiteFuel {
  site: Site
  bulk: TankState[]
  day: TankState[]
  bulk_capacity_l: number
  /** Summed over REPORTING bulk tanks only. Null if none are reporting. */
  bulk_level_l: number | null
  bulk_level_pct: number | null
  /** Compare these two: a total over a partial set understates the site. */
  bulk_tanks_reporting: number
  bulk_tanks_total: number
}

/**
 * One site rolled up to a single row — what a map pin represents.
 *
 * Levels are summed over tanks that have EVER reported, and the reporting/total
 * counts say how many that was.
 *
 * `dark_sensors` is a SEPARATE question and must be read alongside them: a tank
 * counts as reporting on the strength of its last measurement however old, so a
 * site can return `bulk_tanks_reporting === bulk_tanks_total` while every one of
 * those sensors is dark. Treat any dark sensor as making the totals unverified —
 * `reporting === total` is not proof they are current.
 */
export interface SiteSummary {
  site: Site
  generator_count: number
  running_count: number

  bulk_capacity_l: number
  /** Summed over reporting bulk tanks. Null when none has ever reported. */
  bulk_level_l: number | null
  bulk_level_pct: number | null
  bulk_tanks_reporting: number
  bulk_tanks_total: number
  /** Strictest reorder line in the tier — pass to `tankState()`. */
  bulk_reorder_threshold_pct: number

  day_capacity_l: number
  day_level_l: number | null
  day_level_pct: number | null
  day_tanks_reporting: number
  day_tanks_total: number
  day_reorder_threshold_pct: number

  /** Tanks in either tier whose sensor has gone quiet. See the note above. */
  dark_sensors: number

  consumed_l_24h: number
  /** DELIVERY into bulk plus REFILL into a generator tank. TRANSFER excluded. */
  delivered_l_24h: number
  /** Positive magnitudes. Three fields because they are three different claims. */
  drained_l_24h: number
  short_delivery_l_24h: number
  unverified_loss_l_24h: number

  as_of: string
}

export interface GeneratorDetail extends Generator {
  site: Site
  /** The instrumented day tank. Null if the generator has no tank row. */
  day_tank: TankState | null
  /** Null only when the generator has never produced a reading. */
  latest: Reading | null
  /** Null when `latest` is null OR the engine is off. Never fabricate a value here. */
  hours_to_empty: number | null
}

export interface Event {
  id: string
  /**
   * NULL for site-level events — a DELIVERY into shared bulk storage, or a
   * bulk sensor dropping signal, belongs to no single generator.
   */
  generator_id: string | null
  /** Which tank. Null for engine start/stop, which belong to the generator. */
  tank_id: string | null
  /** Set for tractor events; then generator_id and tank_id are null. */
  vehicle_id?: string | null
  event_type: EventType
  occurred_at: string
  /** Signed: positive for fuel in, negative for fuel out, null for state events. */
  volume_l: number | null
  fuel_level_l: number | null
  detail: Record<string, unknown>
}

/** Keyset pagination. Pass `next_cursor` back as `before`; null means the end. */
export interface Page<T> {
  items: T[]
  next_cursor: string | null
}

export interface FleetSummary {
  generator_count: number
  running_count: number
  total_capacity_l: number
  total_fuel_l: number
  fill_pct: number
  below_reorder_threshold: number
  consumed_l_24h: number
  refilled_l_24h: number
  /** Reported as a positive magnitude, though events store drains negative. */
  drained_l_24h: number
  as_of: string
}

export interface DailyConsumption {
  /** UTC midnight of the bucket, as a full datetime. */
  day: string
  consumed_l: number
  runtime_hours: number
  refilled_l: number
  drained_l: number
}

export interface GeneratorConsumption {
  generator_id: string
  generator_name: string
  /** ASCENDING by day — the opposite of the readings and events endpoints. */
  days: DailyConsumption[]
  total_consumed_l: number
  total_refilled_l: number
  total_drained_l: number
}

export interface SimulateResult {
  generator_id: string
  steps: number
  readings: number
  events: EventType[]
  fuel_level_l: number
  fuel_level_pct: number
  /** Set when the request moved the tank before the engine would act. */
  staged_from_l: number | null
  simulated_from: string
  simulated_to: string
}

// --- demo accounts -------------------------------------------------------

/** Where an entity's simulated data stream stands. Only LIVE has history. */
export type StreamStatus = 'PENDING' | 'BACKFILLING' | 'LIVE' | 'FAILED'

export interface DemoLimits {
  max_locations: number
  max_tractors: number
  max_generators_per_location: number
}

export interface RedeemResult {
  /** Shown once. Only its hash is stored server-side. */
  api_key: string
  organisation: { id: string; name: string; slug: string }
  expires_at: string
  limits: DemoLimits
}

export interface DemoEntity {
  type: 'location' | 'tractor'
  id: string
  name: string
  simulation_status: StreamStatus
  progress: number
  error: string | null
}

export interface DemoStatus {
  organisation: { id: string; name: string; slug: string }
  is_demo: boolean
  expires_at: string | null
  days_left: number | null
  limits: DemoLimits | null
  usage: { locations: number; tractors: number }
  entities: DemoEntity[]
  generating: boolean
}

export interface GeneratorInput {
  name: string
  kva_rating: number
  day_tank_capacity_l: number
}

export interface LocationInput {
  name: string
  profile: SiteProfile
  latitude: number
  longitude: number
  address?: string
  generators: GeneratorInput[]
  bulk_tanks: { capacity_l: number }[]
}

export type FieldOperation = 'PLOUGHING' | 'HARROWING' | 'SOWING' | 'SPRAYING' | 'TRANSPORT'

export interface TractorInput {
  name: string
  make_model?: string
  engine_kw: number
  tank_capacity_l: number
  yard: { latitude: number; longitude: number }
  field: { latitude: number; longitude: number; width_m: number; length_m: number; heading_deg: number }
  primary_operation: FieldOperation
  working_hours_start: number
  working_hours_end: number
}

export interface Provisioned {
  type: 'location' | 'tractor'
  id: string
  name: string
  simulation_status: StreamStatus
}

// --- vehicles ------------------------------------------------------------

export type VehicleOperation =
  | FieldOperation
  | 'IDLE'
  | 'TRANSIT'
  | 'REFUELING'
  | 'OFF'

export interface VehicleReading {
  time: string
  latitude: number
  longitude: number
  speed_kmh: number
  heading_deg: number
  engine_on: boolean
  rpm: number
  fuel_level_l: number
  fuel_level_pct: number
  fuel_rate_lph: number
  coolant_c: number
  oil_kpa: number
  engine_hours: number
  operation: VehicleOperation
}

export interface Vehicle {
  id: string
  name: string
  kind: 'TRACTOR'
  make_model: string | null
  serial: string
  engine_kw: number
  tank_capacity_l: number
  fuel_sensor_model: string
  fuel_sensor_serial: string
  calibrated_at: string
  yard_latitude: number
  yard_longitude: number
  field_latitude: number
  field_longitude: number
  field_width_m: number
  field_length_m: number
  field_heading_deg: number
  primary_operation: FieldOperation
  working_hours_start: number
  working_hours_end: number
  utc_offset_hours: number
  simulation_status: StreamStatus
  backfill_progress: number
  last_seen_at: string | null
  /** Null until the machine has reported in the last day. */
  latest: VehicleReading | null
}

export interface VehicleDetail extends Vehicle {
  /** [lat, lon] corners, closed ring. */
  field_polygon: [number, number][]
  today: {
    engine_hours: number
    distance_km: number
    area_ha: number
    consumed_l: number
    l_per_ha: number | null
    quota_l_per_ha: number | null
  }
}

export interface VehicleSeriesPoint {
  time: string
  fuel_level_l: number | null
  fuel_rate_lph: number | null
  rpm: number | null
  speed_kmh: number | null
  coolant_c: number | null
  oil_kpa: number | null
  consumed_l: number
  area_ha: number
}

export interface VehicleSeries {
  vehicle_id: string
  bucket_minutes: number
  start: string
  end: string
  points: VehicleSeriesPoint[]
}

export interface VehicleTrack {
  vehicle_id: string
  start: string
  end: string
  points: number
  /** Coordinates are [lon, lat] — GeoJSON order. */
  segments: { operation: VehicleOperation; coordinates: [number, number][] }[]
}
