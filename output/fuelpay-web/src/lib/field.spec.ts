import { describe, expect, it } from 'vitest'

import { fieldPolygon, haversineM, hectares } from './field'

const FIELD = { latitude: 9.07, longitude: 7.47, width_m: 400, length_m: 600, heading_deg: 30 }

describe('fieldPolygon', () => {
  it('is a closed ring of four corners', () => {
    const ring = fieldPolygon(FIELD)
    expect(ring).toHaveLength(5)
    expect(ring[0]).toEqual(ring[4])
  })

  it('has sides matching length and width', () => {
    const [a, b, c] = fieldPolygon(FIELD)
    expect(haversineM(...a!, ...b!)).toBeCloseTo(600, -1)
    expect(haversineM(...b!, ...c!)).toBeCloseTo(400, -1)
  })

  it('agrees with the server geometry for a known corner', () => {
    // app/simulation/field.py field_polygon(...)[0] for the same field.
    const [lat, lon] = fieldPolygon(FIELD)[0]!
    expect(lat).toBeCloseTo(9.0685644, 6)
    expect(lon).toBeCloseTo(7.4670599, 6)
  })
})

it('hectares', () => {
  expect(hectares(FIELD)).toBe(24)
})
