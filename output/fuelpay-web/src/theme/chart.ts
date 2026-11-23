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

const LIGHT: ChartTokens = {
  axis: '#C6D0DC',
  split: '#EEF2F6',
  text: '#4B5A6E',
  textStrong: '#0B1B2B',
  tooltipBg: '#FFFFFF',
  tooltipBorder: '#DDE4EC',
  markHalo: '#FFFFFF',
  fuel: '#2a78d6',
  fuelArea: 'rgba(42,120,214,0.10)',
  load: '#5A6879',
  loadArea: 'rgba(90,104,121,0.09)',
  ok: '#0E7C5A',
  watch: '#D2760F',
  critical: '#96161F',
  bandDrain: 'rgba(150,22,31,0.13)',
  bandRefill: 'rgba(14,124,90,0.11)',
  zoomFill: 'rgba(42,120,214,0.10)',
}

const DARK: ChartTokens = {
  axis: '#2C3A4D',
  split: '#1A2534',
  text: '#9AAABE',
  textStrong: '#E9EFF6',
  tooltipBg: '#121C2A',
  tooltipBorder: '#2C3A4D',
  markHalo: '#121C2A',
  fuel: '#3987e5',
  fuelArea: 'rgba(57,135,229,0.14)',
  load: '#94A3B8',
  loadArea: 'rgba(148,163,184,0.10)',
  ok: '#2FA985',
  watch: '#B78A20',
  critical: '#CC2A46',
  bandDrain: 'rgba(204,42,70,0.20)',
  bandRefill: 'rgba(47,169,133,0.16)',
  zoomFill: 'rgba(57,135,229,0.14)',
}

export const chartTokens = (mode: Mode): ChartTokens => (mode === 'dark' ? DARK : LIGHT)
