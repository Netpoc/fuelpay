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
  // Ankara accent set: terracotta, saffron, green, indigo, violet; idle
  // states in Netpoc mist so working operations always read loudest.
  PLOUGHING: { label: 'Ploughing', color: '#E06236', work: true },
  HARROWING: { label: 'Harrowing', color: '#D99A1E', work: true },
  SOWING: { label: 'Sowing', color: '#3BA55C', work: true },
  SPRAYING: { label: 'Spraying', color: '#5B6BFF', work: true },
  TRANSPORT: { label: 'Haulage', color: '#A64BF4', work: true },
  TRANSIT: { label: 'On the road', color: '#7D78A0', work: false },
  IDLE: { label: 'Idling', color: '#A8A3C4', work: false },
  REFUELING: { label: 'Refuelling', color: '#14A3A0', work: false },
  OFF: { label: 'Parked', color: '#A8A3C4', work: false },
}

export const operationLabel = (op: VehicleOperation | undefined | null) =>
  op ? OPERATION_SPEC[op].label : 'No signal'
