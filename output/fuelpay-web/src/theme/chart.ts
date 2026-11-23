import type { Mode } from './tokens'

/**
 * Chart colours, per theme.
 *
 * ECharts paints to a canvas and cannot read CSS custom properties, so every
 * value the chart uses has to come from here. Before this file the chart
 * carried fourteen hardcoded hex literals and five rgba literals inline in its
 * option object, none of which could follow a theme.
 *
 * The load trace is deliberately ACHROMATIC. Fuel and load are drawn in
 * separate stacked grids and never overlap, so a second hue was decoration —
 * and dropping it removes a pair from the colourblind pairlist entirely.
 */
export interface ChartTokens {
  axis: string
  split: string
  text: string
  textStrong: string
  tooltipBg: string
  tooltipBorder: string
  /** Halo around incident markers. Must be the SURFACE, never white — a white
   *  ring on a dark card is the most visible dark-mode defect on this screen. */
  markHalo: string
  fuel: string
  fuelArea: string
  load: string
  loadArea: string
  ok: string
  watch: string
  critical: string
  bandDrain: string
  bandRefill: string
  zoomFill: string
}

// Fuel is drawn in Netpoc indigo: it must not share a hue with any status
// (saffron is both the brand accent and close to `watch`), and indigo passes
// the colourblind gate alongside the three status marks.
const LIGHT: ChartTokens = {
  axis: '#D2C8B3',
  split: '#EFEADF',
  text: '#4A4566',
  textStrong: '#14122B',
  tooltipBg: '#FFFDF8',
  tooltipBorder: '#E4DDCD',
  markHalo: '#FFFDF8',
  fuel: '#4450D8',
  fuelArea: 'rgba(68,80,216,0.10)',
  load: '#5B5677',
  loadArea: 'rgba(91,86,119,0.09)',
  ok: '#0E7C5A',
  watch: '#C9700C',
  critical: '#A3172A',
  bandDrain: 'rgba(163,23,42,0.12)',
  bandRefill: 'rgba(14,124,90,0.11)',
  zoomFill: 'rgba(68,80,216,0.10)',
}

const DARK: ChartTokens = {
  axis: 'rgba(245,242,234,0.18)',
  split: 'rgba(245,242,234,0.07)',
  text: '#B6B2CF',
  textStrong: '#F5F2EA',
  tooltipBg: '#1D1A3A',
  tooltipBorder: 'rgba(245,242,234,0.16)',
  markHalo: '#14122B',
  fuel: '#7480FF',
  fuelArea: 'rgba(116,128,255,0.16)',
  load: '#948FB6',
  loadArea: 'rgba(148,143,182,0.10)',
  ok: '#22A98A',
  watch: '#B78A20',
  critical: '#CC2A46',
  bandDrain: 'rgba(204,42,70,0.20)',
  bandRefill: 'rgba(34,169,138,0.16)',
  zoomFill: 'rgba(116,128,255,0.16)',
}

export const chartTokens = (mode: Mode): ChartTokens => (mode === 'dark' ? DARK : LIGHT)

/** Canvas text can't read CSS vars either: Netpoc's Manrope, by name. */
export const CHART_FONT = "'Manrope Variable', 'Manrope', ui-sans-serif, system-ui, sans-serif"
