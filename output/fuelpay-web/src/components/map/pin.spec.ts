import { describe, expect, it } from 'vitest'

import { pinView, sitePinHtml, worstState } from './pin'
import type { SiteMapRow } from '@/stores/sites'
import type { Site, SiteSummary } from '@/api/types'
import type { Incident } from '@/lib/incidents'

const SITE: Site = {
  id: 'site-1',
  name: 'Ikeja Branch',
  profile: 'BANK_BRANCH',
  latitude: 6.6018,
  longitude: 3.3515,
  address: '12 Obafemi Awolowo Way',
}

function summary(over: Partial<SiteSummary> = {}): SiteSummary {
  return {
    site: SITE,
    generator_count: 2,
    running_count: 1,
    bulk_capacity_l: 10_000,
    bulk_level_l: 6200,
    bulk_level_pct: 62,
    bulk_tanks_reporting: 2,
    bulk_tanks_total: 2,
    bulk_reorder_threshold_pct: 25,
    day_capacity_l: 3750,
    day_level_l: 1800,
    day_level_pct: 48,
    day_tanks_reporting: 2,
    day_tanks_total: 2,
    day_reorder_threshold_pct: 25,
    dark_sensors: 0,
    consumed_l_24h: 580,
    delivered_l_24h: 0,
    drained_l_24h: 0,
    short_delivery_l_24h: 0,
    unverified_loss_l_24h: 0,
    as_of: '2026-08-27T12:00:00Z',
    ...over,
  }
}

function row(over: Partial<SiteMapRow> = {}): SiteMapRow {
  return {
    site: SITE,
    summary: summary(),
    bulk: undefined,
    dayTanks: [],
    generators: [],
    running: 1,
    state: 'ok',
    darkSensors: 0,
    partial: false,
    alerts: [],
    ...over,
  }
}

const alert = (event_type: Incident['event_type']): Incident => ({
  id: 'inc-1',
  generator_id: null,
  tank_id: 'tank-1',
  subject: 'tank-1',
  event_type,
  occurred_at: '2026-08-27T10:00:00Z',
  ended_at: '2026-08-27T10:30:00Z',
  volume_l: -220,
  fuel_level_l: 4000,
  count: 3,
  detail: {},
})

describe('pinView', () => {
  it('labels the pin with the bulk percentage', () => {
    expect(pinView(row()).label).toBe('62%')
  })

  it('falls back to the day tier when a site has no bulk storage', () => {
    const view = pinView(
      row({ summary: summary({ bulk_tanks_total: 0, bulk_level_pct: null, bulk_level_l: null }) }),
    )

    expect(view.label).toBe('48%')
  })

  it('separates watch from low by fill weight, since they share a hue', () => {
    expect(pinView(row({ state: 'watch' })).weight).toBe('soft')
    expect(pinView(row({ state: 'low' })).weight).toBe('solid')
  })

  describe('the unknown degrade', () => {
    it('degrades when a sensor is dark, even though every tank still "reports"', () => {
      // The level behind a reporting count is the last one measured, however
      // old — the query has no time bound. So reporting === total is NOT proof
      // the number is current, and a pin cannot carry that caveat in small
      // print. This is the rule that stops a site with every sensor dark
      // showing a confident green pin.
      const view = pinView(
        row({
          state: 'ok',
          darkSensors: 2,
          summary: summary({ dark_sensors: 2, bulk_tanks_reporting: 2, bulk_tanks_total: 2 }),
        }),
      )

      expect(view.unknown).toBe(true)
      expect(view.ariaLabel).toContain('2 sensors not reporting')
    })

    it('degrades when a tier was summed over only some of its tanks', () => {
      expect(pinView(row({ partial: true })).unknown).toBe(true)
    })

    it('degrades when there is no level at all', () => {
      const view = pinView(
        row({
          state: undefined,
          summary: summary({ bulk_level_pct: null, bulk_level_l: null, day_level_pct: null }),
        }),
      )

      expect(view.unknown).toBe(true)
      expect(view.label).toBe('—')
    })

    it('does not degrade a healthy, fully-reporting site', () => {
      expect(pinView(row()).unknown).toBe(false)
    })
  })

  it('badges the worst live incident and keeps its severity', () => {
    const drain = pinView(row({ alerts: [alert('SUSPECTED_DRAIN')] }))
    expect(drain.badge).toBe('▼')
    expect(drain.badgeState).toBe('critical')

    const signal = pinView(row({ alerts: [alert('SIGNAL_LOSS')] }))
    expect(signal.badgeState).toBe('watch')
  })

  it('builds an aria-label carrying everything the pin encodes visually', () => {
    const view = pinView(
      row({ state: 'low', generators: [], running: 1, alerts: [alert('SUSPECTED_DRAIN')] }),
    )

    expect(view.ariaLabel).toContain('Ikeja Branch')
    expect(view.ariaLabel).toContain('62 percent')
    expect(view.ariaLabel).toContain('Below reorder')
    expect(view.ariaLabel).toContain('Suspected drain')
  })
})

describe('sitePinHtml', () => {
  it('carries the state as an attribute so CSS resolves the colour', () => {
    const html = sitePinHtml(pinView(row({ state: 'critical' })))

    expect(html).toContain('data-state="critical"')
    expect(html).toContain('fp-pin--solid')
  })

  it('escapes text rather than interpolating it raw', () => {
    const html = sitePinHtml(pinView(row({ site: { ...SITE, name: '<script>x</script>' } })))

    expect(html).not.toContain('<script>')
  })
})

describe('worstState', () => {
  it('returns the worst child, never an average', () => {
    const views = [
      pinView(row({ state: 'ok' })),
      pinView(row({ state: 'critical' })),
      pinView(row({ state: 'ok' })),
    ]

    expect(worstState(views)).toBe('critical')
  })

  it('ignores children with no measurable state', () => {
    const views = [pinView(row({ state: undefined })), pinView(row({ state: 'watch' }))]

    expect(worstState(views)).toBe('watch')
  })
})
