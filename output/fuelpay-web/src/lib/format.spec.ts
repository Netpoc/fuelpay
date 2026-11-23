import { describe, expect, it } from 'vitest'

import { hoursToEmpty, litres, relativeTime, secondsSince, signedLitres } from './format'

describe('secondsSince', () => {
  it('never goes negative for a future timestamp', () => {
    // Not defensive padding: run_span steps until it passes its target, so the
    // newest reading can be timestamped up to one tick ahead of wall-clock.
    // Unclamped, a live dashboard reads "updated -180s ago".
    const now = Date.now()
    const future = new Date(now + 4 * 60_000).toISOString()
    expect(secondsSince(future, now)).toBe(0)
  })

  it('measures elapsed time normally', () => {
    const now = Date.now()
    const past = new Date(now - 90_000).toISOString()
    expect(secondsSince(past, now)).toBeCloseTo(90)
  })
})

describe('relativeTime', () => {
  const now = Date.parse('2026-08-03T12:00:00Z')
  const ago = (ms: number) => new Date(now - ms).toISOString()

  it('reads a future reading as "just now" rather than negative', () => {
    expect(relativeTime(new Date(now + 200_000).toISOString(), now)).toBe('just now')
  })

  it('scales through minutes, hours and days', () => {
    expect(relativeTime(ago(10_000), now)).toBe('just now')
    expect(relativeTime(ago(5 * 60_000), now)).toBe('5m ago')
    expect(relativeTime(ago(3 * 3_600_000), now)).toBe('3h ago')
    expect(relativeTime(ago(2 * 86_400_000), now)).toBe('2d ago')
  })
})

describe('litres', () => {
  it('drops to whole numbers above 100, where a decimal is false precision', () => {
    expect(litres(42.37)).toBe('42.4 L')
    expect(litres(1167.4)).toBe('1,167 L')
  })

  it('renders absent values as a dash', () => {
    expect(litres(null)).toBe('—')
    expect(litres(undefined)).toBe('—')
  })
})

describe('signedLitres', () => {
  it('signs refills and drains distinctly', () => {
    expect(signedLitres(312)).toBe('+312 L')
    expect(signedLitres(-287)).toBe('−287 L')
  })

  it('uses a true minus sign, not a hyphen, so digits stay aligned', () => {
    expect(signedLitres(-287).charCodeAt(0)).toBe(0x2212)
  })

  it('renders engine events, which carry no volume, as a dash', () => {
    expect(signedLitres(null)).toBe('—')
  })
})

describe('hoursToEmpty', () => {
  it('never invents a figure when the engine is off', () => {
    // The API returns null here because runtime-remaining at zero load is not
    // finite. Substituting a number would claim an autonomy the unit lacks.
    expect(hoursToEmpty(null)).toBe('—')
  })

  it('switches units so the number stays readable', () => {
    expect(hoursToEmpty(0.5)).toBe('30 min')
    expect(hoursToEmpty(8.24)).toBe('8.2 h')
    expect(hoursToEmpty(72)).toBe('3 d')
  })
})
