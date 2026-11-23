import { describe, expect, it } from 'vitest'

import {
  BOTTOM_Y,
  MAJOR_PCT,
  MINOR_PCT,
  SPAN,
  TOP_Y,
  fillFraction,
  surfaceY,
  thresholdY,
} from './geometry'
import { RUNNING_AGITATION, STILL_AGITATION, surfaceScale } from './wave'
import { tankState } from './state'

describe('geometry', () => {
  it('puts a full tank at the rim and an empty one at the floor', () => {
    // SVG y grows downward, so fuller means a smaller y. Getting this backwards
    // renders a tank that drains upward.
    expect(surfaceY(1)).toBe(TOP_Y)
    expect(surfaceY(0)).toBe(BOTTOM_Y)
    expect(surfaceY(0.5)).toBe(TOP_Y + SPAN / 2)
  })

  it('clamps out-of-range fractions', () => {
    // Sensor noise can report just over 100% or just under 0.
    expect(surfaceY(1.04)).toBe(TOP_Y)
    expect(surfaceY(-0.02)).toBe(BOTTOM_Y)
  })

  it('places scale graduations on the same mapping as the surface', () => {
    // If these diverged, the fuel would read against the wrong number — the
    // one failure this component cannot survive.
    expect(thresholdY(100)).toBe(surfaceY(1))
    expect(thresholdY(0)).toBe(surfaceY(0))
    expect(thresholdY(30)).toBeCloseTo(surfaceY(0.3))
  })

  it('survives a zero capacity instead of producing NaN geometry', () => {
    expect(fillFraction(50, 0)).toBe(0)
    expect(Number.isNaN(surfaceY(fillFraction(50, 0)))).toBe(false)
  })

  it('converts litres to a fraction', () => {
    expect(fillFraction(583.5, 1167)).toBeCloseTo(0.5)
  })
})

describe('calibration scale', () => {
  it('labels the quarters', () => {
    expect(MAJOR_PCT).toEqual([100, 75, 50, 25, 0])
  })

  it('never repeats a labelled graduation as a minor one', () => {
    // A minor tick drawn under a major one renders as a thickened smudge.
    for (const pct of MINOR_PCT) expect(MAJOR_PCT).not.toContain(pct)
  })

  it('spaces minor graduations every five percent', () => {
    expect(MINOR_PCT).toHaveLength(16)
    for (const pct of MINOR_PCT) expect(pct % 5).toBe(0)
  })
})

describe('surface agitation', () => {
  it('is flat when the engine is stopped', () => {
    const { x, y } = surfaceScale(STILL_AGITATION)
    expect(x).toBe(1)
    expect(y).toBe(1)
  })

  it('moves the minor radius more than the major one', () => {
    // A surface rocking towards and away from the viewer changes its apparent
    // depth far more than its width. Scaling both equally reads as the whole
    // tank pulsing.
    const { x, y } = surfaceScale(RUNNING_AGITATION)
    expect(y).toBeGreaterThan(x)
  })

  it('stays subtle — this is a day tank, not a sea', () => {
    expect(surfaceScale(RUNNING_AGITATION).y).toBeLessThan(1.15)
  })
})

describe('tank state', () => {
  // The seeded fleet uses 20 / 25 / 30 percent thresholds, so classification
  // must be relative to each generator rather than to a fixed number.
  it('classifies against the generator’s own threshold', () => {
    expect(tankState(60, 30)).toBe('ok')
    expect(tankState(40, 30)).toBe('watch')
    expect(tankState(28, 30)).toBe('low')
    expect(tankState(4, 30)).toBe('critical')
  })

  it('gives the same fill different states under different thresholds', () => {
    expect(tankState(28, 30)).toBe('low')
    expect(tankState(28, 20)).toBe('watch')
  })

  it('treats a near-dry tank as critical whatever the threshold', () => {
    expect(tankState(3, 20)).toBe('critical')
    expect(tankState(3, 30)).toBe('critical')
  })

  it('puts the boundary exactly at the threshold', () => {
    expect(tankState(30, 30)).toBe('watch')
    expect(tankState(29.9, 30)).toBe('low')
  })
})
