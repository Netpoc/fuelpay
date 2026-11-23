import { get } from './client'
import type { Event, Page, Vehicle, VehicleDetail, VehicleSeries, VehicleTrack } from './types'

export const listVehicles = () => get<Vehicle[]>('/vehicles')

export const getVehicle = (id: string) => get<VehicleDetail>(`/vehicles/${id}`)

export const getVehicleSeries = (id: string, hours: number) =>
  get<VehicleSeries>(`/vehicles/${id}/series`, { hours })

export const getVehicleTrack = (id: string, hours: number) =>
  get<VehicleTrack>(`/vehicles/${id}/track`, { hours })

export const listVehicleEvents = (id: string, params: Record<string, unknown> = {}) =>
  get<Page<Event>>('/events', { vehicle_id: id, limit: 500, ...params })
