/**
 * Tank geometry, in viewBox units.
 *
 * A standing cylinder seen slightly from above: two ellipses joined by
 * straight walls. Coordinates follow the reference drawing directly so the
 * proportions are preserved at every rendered size — the wrapper's width and
 * height do the scaling and nothing here knows about pixels.
 */

export const CX = 340
export const RX = 128
/** Ellipse minor radius. The ratio to RX is what sets the viewing angle. */
export const RY = 30

/** Centres of the rim and floor ellipses. */
export const TOP_Y = 90
export const BOTTOM_Y = 380
/** Vertical distance a full tank's surface travels from empty to full. */
export const SPAN = BOTTOM_Y - TOP_Y

export const LEFT = CX - RX
export const RIGHT = CX + RX

// --- calibration scale, to the right of the tank ---
export const SCALE_X = 510
export const MAJOR_TICK_X = 530
export const MINOR_TICK_X = 520
export const LABEL_X = 538

/** Labelled graduations. */
export const MAJOR_PCT = [100, 75, 50, 25, 0]
/** Unlabelled graduations between them, every 5%. */
export const MINOR_PCT = Array.from({ length: 21 }, (_, i) => i * 5).filter(
  (pct) => pct % 25 !== 0,
)

export const clamp01 = (value: number) => Math.min(1, Math.max(0, value))

/**
 * The y coordinate of the liquid surface for a given fill fraction.
 *
 * SVG y grows downward, so a fuller tank has a SMALLER y. Full sits at the rim
 * ellipse, empty at the floor ellipse.
 */
export function surfaceY(fraction: number): number {
  return BOTTOM_Y - clamp01(fraction) * SPAN
}

/** Where a percentage sits on the scale — the same mapping as the surface. */
export function thresholdY(pct: number): number {
  return surfaceY(pct / 100)
}

/**
 * Fill fraction from litres.
 *
 * Guards a zero capacity: a generator row with a bad tank size should render
 * an empty tank, not NaN geometry that collapses the whole drawing.
 */
export function fillFraction(levelL: number, capacityL: number): number {
  if (!capacityL || capacityL <= 0) return 0
  return clamp01(levelL / capacityL)
}

/**
 * viewBox for each layout.
 *
 * The compact one crops to the cylinder alone. At the size a fleet card gives
 * it, the scale's "100%" labels would render around four pixels tall — present
 * but unreadable, which is worse than absent.
 */
export const VIEWBOX = {
  compact: '196 52 296 372',
  full: '196 52 466 372',
} as const

/**
 * Level badge, clear of the scale labels.
 *
 * Sitting it directly beside the numbers collided with them whenever the level
 * landed near a labelled graduation — which is exactly when an operator is
 * reading both. The gap is not cosmetic.
 */
export const BADGE_X = 584
export const BADGE_W = 58
/** Where the level's leader line stops, just short of the badge. */
export const LEADER_END = BADGE_X - 6
