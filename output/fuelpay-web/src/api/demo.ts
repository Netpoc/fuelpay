/**
 * Coupon-gated demo accounts.
 *
 * `redeem` is the only call made without a key — it is what produces one.
 */
import { get, post } from './client'
import type {
  DemoStatus,
  LocationInput,
  Provisioned,
  RedeemResult,
  TractorInput,
} from './types'

export const redeemCoupon = (body: { code: string; company_name: string; contact_email?: string }) =>
  post<RedeemResult>('/demo/redeem', body)

export const getDemoStatus = () => get<DemoStatus>('/demo/status')

export const createLocation = (body: LocationInput) => post<Provisioned>('/demo/locations', body)

export const createTractor = (body: TractorInput) => post<Provisioned>('/demo/tractors', body)
