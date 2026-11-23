/**
 * Surface agitation.
 *
 * The liquid surface is an ellipse — the top of a cylinder seen at an angle —
 * not a wavy line, so there is no sine path to generate here. A running engine
 * vibrates the tank and the surface trembles; a stopped one settles flat.
 *
 * That trembling is expressed as a small scale on the surface ellipse, driven
 * by a CSS keyframe. It runs on the compositor at no per-frame JS cost, which
 * matters when a fleet grid holds twelve of these. A requestAnimationFrame
 * loop redrawing ellipses every frame is how a dashboard drops to 20fps, and
 * SMIL cannot be switched off by a `prefers-reduced-motion` media query —
 * which is the whole reduced-motion story.
 */

/**
 * Peak deviation of the surface ellipse's minor radius while running, as a
 * fraction of it.
 *
 * The reference doc puts sloshing at about 0.5% of capacity, so this stays
 * deliberately small. A heaving sea inside a diesel day tank would be
 * decoration, not information.
 */
export const RUNNING_AGITATION = 0.09
export const STILL_AGITATION = 0

/** Below this the surface is treated as flat and nothing is composited. */
export const AGITATION_EPSILON = 0.004

/**
 * Scale factors for the surface ellipse at a given agitation.
 *
 * Returned as a pair because the trembling is anisotropic: the minor radius
 * moves noticeably while the major radius barely does, which is what a liquid
 * surface rocking towards and away from the viewer actually looks like.
 */
export function surfaceScale(agitation: number): { x: number; y: number } {
  return { x: 1 + agitation * 0.12, y: 1 + agitation }
}
