/**
 * The admin console's API client.
 *
 * Same request core as the tenant client, different credential: the admin
 * session travels as `X-Admin-Token`, and a 401 returns to the admin sign-in.
 */
import { queryString, send } from './client'
import type {
  Admin,
  AdminRole,
  AuditPage,
  Coupon,
  CouponDetail,
  CouponInput,
  IssuedKey,
  LoginResult,
  Me,
  Overview,
  SystemStatus,
  TenantDetail,
  TenantKey,
  TenantKind,
  TenantRow,
  TickSummary,
  Tuning,
} from './adminTypes'

let token: string | null = null
const failureHandlers = new Set<() => void>()

export const setAdminToken = (value: string | null) => (token = value)
export function onAdminUnauthorized(handler: () => void) {
  failureHandlers.add(handler)
  return () => failureHandlers.delete(handler)
}

function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  return send<T>(`/platform${path}`, init, token ? { 'X-Admin-Token': token } : {}, () => {
    for (const handler of failureHandlers) handler()
  })
}
const json = (method: string, body?: unknown): RequestInit => ({
  method,
  body: body === undefined ? undefined : JSON.stringify(body),
})

// auth
export const login = (email: string, password: string) =>
  call<LoginResult>('/auth/login', json('POST', { email, password }))
export const logout = () => call<void>('/auth/logout', json('POST'))
export const me = () => call<Me>('/auth/me')

// overview & system
export const getOverview = () => call<Overview>('/overview')
export const getSystem = () => call<SystemStatus>('/system')
export const runTick = () => call<TickSummary>('/system/tick', json('POST'))
export const runExpiry = () =>
  call<{ keys_revoked: number; tenants_purged: number }>('/system/expire-now', json('POST'))
export const retryBackfill = (kind: 'location' | 'tractor', id: string) =>
  call<{ queued: boolean }>(`/system/backfills/${kind}/${id}/retry`, json('POST'))
export const getTuning = () => call<Tuning>('/settings/tuning')
export const putTuning = (overrides: Tuning['overrides']) =>
  call<Tuning>('/settings/tuning', json('PUT', { overrides }))

// tenants
export const listTenants = (params: { kind?: TenantKind; q?: string } = {}) =>
  call<TenantRow[]>(`/tenants${queryString(params)}`)
export const getTenant = (id: string) => call<TenantDetail>(`/tenants/${id}`)
export const createTenant = (body: { name: string; slug?: string; key_label?: string }) =>
  call<{ tenant: TenantRow; key: IssuedKey }>('/tenants', json('POST', body))
export const issueKey = (id: string, label: string) =>
  call<IssuedKey>(`/tenants/${id}/keys`, json('POST', { label }))
export const revokeKey = (id: string, keyId: string) =>
  call<TenantKey>(`/tenants/${id}/keys/${keyId}`, json('DELETE'))
export const extendDemo = (id: string, days: number) =>
  call<TenantRow>(`/tenants/${id}/extend`, json('POST', { days }))
export const convertDemo = (id: string) => call<TenantRow>(`/tenants/${id}/convert`, json('POST'))
export const purgeTenant = (id: string, confirmName: string) =>
  call<void>(`/tenants/${id}`, json('DELETE', { confirm_name: confirmName }))

// coupons
export const listCoupons = () => call<Coupon[]>('/coupons')
export const getCoupon = (id: string) => call<CouponDetail>(`/coupons/${id}`)
export const createCoupon = (body: CouponInput) => call<Coupon>('/coupons', json('POST', body))
export const updateCoupon = (id: string, body: Partial<CouponInput> & { is_active?: boolean }) =>
  call<Coupon>(`/coupons/${id}`, json('PATCH', body))

// admins & audit
export const listAdmins = () => call<Admin[]>('/admins')
export const createAdmin = (body: { email: string; name: string; password: string; role: AdminRole }) =>
  call<Admin>('/admins', json('POST', body))
export const updateAdmin = (
  id: string,
  body: Partial<{ name: string; role: AdminRole; is_active: boolean; password: string }>,
) => call<Admin>(`/admins/${id}`, json('PATCH', body))
export const listAudit = (params: { before?: string; action?: string; limit?: number } = {}) =>
  call<AuditPage>(`/audit${queryString(params)}`)
