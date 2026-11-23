/** Mirrors app/admin_schemas.py. Cross-tenant shapes; never used by tenant views. */
import type { StreamStatus } from './types'

export type AdminRole = 'OWNER' | 'STAFF'
export type TenantKind = 'real' | 'demo' | 'expired'

export interface Admin {
  id: string | null
  email: string
  name: string
  role: AdminRole
  is_active: boolean
  last_login_at: string | null
  created_at: string | null
}

export interface LoginResult {
  token: string
  expires_at: string
  admin: Admin
}

export interface Me {
  admin: Admin
  break_glass: boolean
}

export interface AuditEntry {
  id: string
  actor_label: string
  action: string
  target_type: string | null
  target_id: string | null
  detail: Record<string, unknown>
  at: string
}

export interface AuditPage {
  items: AuditEntry[]
  next_cursor: string | null
}

export interface TenantRow {
  id: string
  name: string
  slug: string
  kind: TenantKind
  created_at: string
  demo_expires_at: string | null
  converted_at: string | null
  coupon_code: string | null
  sites: number
  generators: number
  tractors: number
  active_keys: number
  last_reading_at: string | null
}

export interface TenantKey {
  id: string
  prefix: string
  label: string
  created_at: string
  revoked_at: string | null
}

export interface TenantDetail extends TenantRow {
  contact_email: string | null
  site_list: {
    id: string
    name: string
    profile: string
    generators: number
    simulation_status: StreamStatus
    backfill_error: string | null
  }[]
  vehicle_list: {
    id: string
    name: string
    serial: string
    simulation_status: StreamStatus
    last_seen_at: string | null
    backfill_error: string | null
  }[]
  keys: TenantKey[]
}

export interface IssuedKey extends TenantKey {
  /** Shown once. */
  api_key: string
}

export interface Coupon {
  id: string
  code: string
  label: string | null
  max_redemptions: number
  redemptions_count: number
  expires_at: string | null
  demo_duration_days: number
  max_locations: number
  max_tractors: number
  max_generators_per_location: number
  is_active: boolean
  created_at: string
  conversions?: number
}

export interface CouponDetail extends Coupon {
  redemptions: {
    id: string
    organisation_id: string | null
    company_name: string
    contact_email: string | null
    redeemed_at: string
  }[]
}

export interface CouponInput {
  code?: string
  label?: string
  max_redemptions: number
  expires_at?: string | null
  demo_duration_days: number
  max_locations: number
  max_tractors: number
  max_generators_per_location: number
}

export interface Overview {
  tenants_real: number
  demos_active: number
  demos_expiring_3d: number
  demos_expired: number
  conversions_30d: number
  redemptions_30d: number
  conversion_rate: number | null
  redemptions_by_day: { day: string; count: number }[]
  readings_24h: number
  incidents_24h: { event_type: string; count: number }[]
  incidents_by_tenant_24h: { organisation_id: string; name: string; count: number }[]
  as_of: string
}

export interface BackfillItem {
  kind: 'location' | 'tractor'
  id: string
  name: string
  organisation: string
  simulation_status: StreamStatus
  progress: number
  error: string | null
}

export interface TickSummary {
  started_at: string
  sites: number
  generators: number
  vehicles: number
  readings: number
  vehicle_readings: number
  events: number
  skipped_locked: boolean
}

export interface SystemStatus {
  sim_enabled: boolean
  tick_seconds: number
  max_lag_seconds: number | null
  last_tick: TickSummary | null
  backfills: BackfillItem[]
  database_bytes: number
  tables: { name: string; bytes: number }[]
  disk_total_bytes: number
  disk_free_bytes: number
  as_of: string
}

export type TuningGroup = Record<string, number>
export interface Tuning {
  effective: { theft: TuningGroup; vehicle: TuningGroup }
  overrides: Partial<{ theft: TuningGroup; vehicle: TuningGroup }>
  defaults: { theft: TuningGroup; vehicle: TuningGroup }
}
