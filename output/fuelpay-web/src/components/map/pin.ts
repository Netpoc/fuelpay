/**
 * What a map pin shows, and the icon that draws it.
 *
 * Pure and separated from the map component so the encoding rules can be tested
 * without a Leaflet instance or a DOM — see pin.spec.ts.
 *
 * Leaflet markers are DOM, not canvas, so unlike the ECharts work in
 * theme/chart.ts this needs no duplicate colour table: the icon carries a
 * `data-state` attribute and the CSS resolves it against the same `--status-*`
 * custom properties everything else uses. A theme switch is one attribute flip
 * on <html> and every pin follows, with no JS repaint.
 */

import L from 'leaflet'

import { STATE_LABEL, type TankState } from '@/components/tank/state'
import { EVENT_SPEC, type Incident } from '@/lib/incidents'
import { percent } from '@/lib/format'
import { STATUS_WEIGHT } from '@/theme/tokens'
import type { SiteMapRow } from '@/stores/sites'

export interface PinView {
  siteId: string
  lat: number
  lng: number
  /** Undefined when nothing at the site is measurable. */
  state: TankState | undefined
  /** Fill weight — the second channel that separates `watch` from `low`. */
  weight: 'soft' | 'solid'
  /**
   * True when no figure here can be trusted as current: either a tier was
   * summed over some of its tanks, or a sensor has gone quiet. Rendered as the
   * dashed "unknown" treatment rather than a colour.
   */
  unknown: boolean
  /** The number on the pin. An em dash when there is no level to show. */
  label: string
  /** Worst live incident's glyph, or null. */
  badge: string | null
  badgeState: 'critical' | 'watch' | null
  selected: boolean
  ariaLabel: string
}

/** Prefer the bulk tier: it is the larger reserve and the one a tanker fills. */
function headlinePct(row: SiteMapRow): number | null {
  const summary = row.summary
  if (summary) {
    if (summary.bulk_tanks_total && summary.bulk_level_pct !== null) return summary.bulk_level_pct
    if (summary.day_tanks_total && summary.day_level_pct !== null) return summary.day_level_pct
    return null
  }
  return row.bulk?.levelPct ?? null
}

function ariaLabelFor(row: SiteMapRow, pct: number | null, unknown: boolean): string {
  const parts: string[] = [row.site.name]

  if (pct === null) {
    parts.push('No level reported')
  } else {
    const tier = row.summary?.bulk_tanks_total ? 'Bulk reserve' : 'Day tanks'
    parts.push(`${tier} ${Math.round(pct)} percent, ${STATE_LABEL[row.state ?? 'ok']}`)
  }

  if (row.generators.length) {
    parts.push(`${row.generators.length} generators, ${row.running} running`)
  }
  if (row.darkSensors) {
    parts.push(`${row.darkSensors} sensor${row.darkSensors === 1 ? '' : 's'} not reporting`)
  } else if (unknown) {
    parts.push('Partial data')
  }

  const worst = row.alerts[0]
  if (worst) parts.push(EVENT_SPEC[worst.event_type].label)

  return `${parts.join('. ')}.`
}

export function pinView(row: SiteMapRow, selected = false): PinView {
  const pct = headlinePct(row)
  // A quiet sensor makes the totals provisional even when every tank counts as
  // "reporting" — the level behind that count is the last one measured, however
  // old. A pin is one glyph and cannot carry the caveat in small print, so it
  // degrades to the unknown treatment instead of showing a confident colour.
  const unknown = pct === null || row.darkSensors > 0 || row.partial
  const worst: Incident | undefined = row.alerts[0]
  const spec = worst ? EVENT_SPEC[worst.event_type] : null

  return {
    siteId: row.site.id,
    lat: row.site.latitude,
    lng: row.site.longitude,
    state: row.state,
    weight: row.state ? STATUS_WEIGHT[row.state] : 'soft',
    unknown,
    label: pct === null ? '—' : percent(pct, 0),
    badge: spec?.glyph || null,
    badgeState: spec ? (spec.status === 'critical' ? 'critical' : 'watch') : null,
    selected,
    ariaLabel: ariaLabelFor(row, pct, unknown),
  }
}

const escape = (value: string) =>
  value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

export function sitePinHtml(view: PinView): string {
  const classes = [
    'fp-pin',
    `fp-pin--${view.weight}`,
    view.unknown ? 'fp-pin--unknown' : '',
    view.selected ? 'fp-pin--selected' : '',
    view.badge ? 'fp-pin--alerting' : '',
  ]
    .filter(Boolean)
    .join(' ')

  const badge = view.badge
    ? `<span class="fp-pin__badge" data-badge="${view.badgeState}" aria-hidden="true">${escape(view.badge)}</span>`
    : ''

  return (
    `<span class="${classes}" data-state="${view.state ?? 'none'}">` +
    `<span class="fp-pin__label">${escape(view.label)}</span>${badge}` +
    `</span>`
  )
}

export function sitePinIcon(view: PinView): L.DivIcon {
  return L.divIcon({
    html: sitePinHtml(view),
    // Namespaced away from `leaflet-div-icon`, whose default white box and
    // border would otherwise frame every pin.
    className: 'fp-pin-icon',
    iconSize: [44, 44],
    iconAnchor: [22, 22],
    popupAnchor: [0, -20],
  })
}

/** Worst state among a cluster's children — never an average. */
export function worstState(views: PinView[]): TankState | undefined {
  const rank: Record<TankState, number> = { critical: 0, low: 1, watch: 2, ok: 3 }
  return views
    .map((view) => view.state)
    .filter((state): state is TankState => state !== undefined)
    .sort((a, b) => rank[a] - rank[b])[0]
}
