import { describe, expect, it } from 'vitest'

import { bytes, duration, untilText } from './adminFormat'

describe('adminFormat', () => {
  it('bytes', () => {
    expect(bytes(512)).toBe('512 B')
    expect(bytes(37_000_000)).toBe('37.0 MB')
    expect(bytes(228_000_000_000)).toBe('228 GB')
  })
  it('duration', () => {
    expect(duration(null)).toBe('—')
    expect(duration(30)).toBe('30 s')
    expect(duration(600)).toBe('10 min')
    expect(duration(44_280)).toBe('12.3 h')
  })
  it('untilText', () => {
    const now = Date.UTC(2026, 9, 29)
    expect(untilText(new Date(now + 3 * 86_400_000).toISOString(), now)).toBe('in 3 days')
    expect(untilText(new Date(now - 86_400_000).toISOString(), now)).toBe('1 day ago')
  })
})
