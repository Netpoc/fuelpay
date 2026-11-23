/**
 * What a tractor is doing, in words and on the map.
 *
 * Track colours sit on the basemap, not on a themed surface, so they are fixed
 * hex rather than tokens: mid-luminance hues that read on both the light and
 * the dark gray canvas. Field work gets the warm, saturated colours; overhead
 * (transit, idling) is grey, because the eye should go to the work.
 */
import type { VehicleOperation } from '@/api/types'

export const OPERATION_SPEC: Record<VehicleOperation, { label: string; color: string; work: boolean }> = {
  PLOUGHING: { label: 'Ploughing', color: '#c0622a', work: true },
  HARROWING: { label: 'Harrowing', color: '#c99a2e', work: true },
  SOWING: { label: 'Sowing', color: '#2f9e6b', work: true },
  SPRAYING: { label: 'Spraying', color: '#2a78d6', work: true },
  TRANSPORT: { label: 'Haulage', color: '#8a63d2', work: true },
  TRANSIT: { label: 'On the road', color: '#64748b', work: false },
  IDLE: { label: 'Idling', color: '#94a3b8', work: false },
  REFUELING: { label: 'Refuelling', color: '#0e7c5a', work: false },
  OFF: { label: 'Parked', color: '#94a3b8', work: false },
}

export const operationLabel = (op: VehicleOperation | undefined | null) =>
  op ? OPERATION_SPEC[op].label : 'No signal'
