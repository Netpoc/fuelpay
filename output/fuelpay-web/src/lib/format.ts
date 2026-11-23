/** Display formatting. Pure, and unit-tested — see format.spec.ts. */

/**
 * Seconds between a reading's timestamp and now, never negative.
 *
 * The clamp is not defensive padding. The simulator's `run_span` steps until it
 * passes its target, so the newest reading can be timestamped up to one tick
 * AHEAD of wall-clock. Without the clamp a live dashboard shows "updated -180s
 * ago", which reads as a bug in the page rather than a property of the data.
 */
export function secondsSince(iso: string, now: number = Date.now()): number {
  return Math.max(0, (now - new Date(iso).getTime()) / 1000)
}

export function relativeTime(iso: string, now: number = Date.now()): string {
  const seconds = secondsSince(iso, now)
  if (seconds < 45) return 'just now'
  const minutes = seconds / 60
  if (minutes < 60) return `${Math.round(minutes)}m ago`
  const hours = minutes / 60
  if (hours < 24) return `${Math.round(hours)}h ago`
  return `${Math.round(hours / 24)}d ago`
}

/**
 * Litres, to one decimal below 100 and whole numbers above.
 *
 * The reference doc is explicit that published consumption figures disagree by
 * 20-40% and real use varies +/-10%, so precision beyond about a litre is
 * false confidence. Sensor quantisation is 0.1 L, which is the floor here.
 */
export function litres(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const rounded = Math.abs(value) < 100 ? value.toFixed(1) : Math.round(value).toLocaleString()
  return `${rounded} L`
}

/** Signed volume, for event feeds: `+312 L` delivered, `−287 L` taken. */
export function signedLitres(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  // U+2212 MINUS SIGN, not a hyphen: it aligns with digits at the same width.
  const sign = value < 0 ? '−' : '+'
  return `${sign}${litres(Math.abs(value))}`
}

export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(digits)}%`
}

/**
 * Projected runtime. Null is rendered, never guessed at.
 *
 * The API returns null whenever the engine is off, because runtime-remaining at
 * zero load is not a finite number. Substituting a dash is honest; substituting
 * a computed figure would invent an autonomy the unit does not have.
 */
export function hoursToEmpty(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value < 1) return `${Math.round(value * 60)} min`
  if (value < 48) return `${value.toFixed(1)} h`
  return `${Math.round(value / 24)} d`
}

export function kilowatts(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(1)} kW`
}

const PROFILE_LABELS: Record<string, string> = {
  TELECOM_TOWER: 'Telecom tower',
  OFFICE: 'Office',
  RESIDENTIAL: 'Residential',
  BANK_BRANCH: 'Bank branch',
}

export const profileLabel = (profile: string) => PROFILE_LABELS[profile] ?? profile
