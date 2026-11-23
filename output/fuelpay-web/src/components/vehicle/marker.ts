/**
 * The tractor's map marker: a chevron pointing where it is heading, coloured by
 * what it is doing. A divIcon, so it is real DOM and needs no sprite.
 */
import L from 'leaflet'

import type { VehicleReading } from '@/api/types'
import { OPERATION_SPEC, operationLabel } from '@/lib/operations'

export function tractorIcon(name: string, latest: VehicleReading | null): L.DivIcon {
  const op = latest?.operation ?? 'OFF'
  const color = OPERATION_SPEC[op].color
  const heading = latest?.heading_deg ?? 0
  const moving = (latest?.speed_kmh ?? 0) > 0.5
  const label = `${name}: ${operationLabel(latest?.operation)}`.replace(/"/g, '&quot;')
  // Parked machines draw a disc: a heading is meaningless when standing still.
  const glyph = moving
    ? `<path d="M14 3 L23 24 L14 19 L5 24 Z" fill="${color}" stroke="#fff" stroke-width="2" stroke-linejoin="round"/>`
    : `<circle cx="14" cy="14" r="8" fill="${color}" stroke="#fff" stroke-width="2.5"/>`
  return L.divIcon({
    html:
      `<span role="img" aria-label="${label}" style="display:block;width:28px;height:28px;` +
      `transform:rotate(${moving ? heading : 0}deg);filter:drop-shadow(0 1px 2px rgba(0,0,0,.35))">` +
      `<svg viewBox="0 0 28 28" width="28" height="28">${glyph}</svg></span>`,
    className: 'fp-tractor-icon',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  })
}
