/**
 * Field geometry, mirroring app/simulation/field.py.
 *
 * A field is an oriented rectangle: a centre, a length along a compass heading
 * and a width across it. The wizard draws it live while the prospect sizes it,
 * so it has to agree with the server's version to the metre — the simulator
 * keeps field work inside exactly this shape.
 */

const METRES_PER_DEGREE_LAT = 111_320

const cosLat = (lat: number) => Math.max(Math.cos((lat * Math.PI) / 180), 1e-6)

export function offsetLatLon(
  lat: number,
  lon: number,
  eastM: number,
  northM: number,
): [number, number] {
  return [lat + northM / METRES_PER_DEGREE_LAT, lon + eastM / (METRES_PER_DEGREE_LAT * cosLat(lat))]
}

export interface Field {
  latitude: number
  longitude: number
  width_m: number
  length_m: number
  /** Long axis, degrees clockwise from north. */
  heading_deg: number
}

/** Corners as [lat, lon], closed ring. */
export function fieldPolygon(field: Field): [number, number][] {
  const h = (field.heading_deg * Math.PI) / 180
  const along = [Math.sin(h), Math.cos(h)]
  const across = [Math.cos(h), -Math.sin(h)]
  const at = (a: number, c: number) =>
    offsetLatLon(
      field.latitude,
      field.longitude,
      a * along[0]! + c * across[0]!,
      a * along[1]! + c * across[1]!,
    )
  const l = field.length_m / 2
  const w = field.width_m / 2
  const corners = [at(-l, -w), at(l, -w), at(l, w), at(-l, w)]
  return [...corners, corners[0]!]
}

/** Great-circle distance in metres. */
export function haversineM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const rad = Math.PI / 180
  const dp = (lat2 - lat1) * rad
  const dl = (lon2 - lon1) * rad
  const a =
    Math.sin(dp / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dl / 2) ** 2
  return 2 * 6_371_000 * Math.asin(Math.sqrt(a))
}

export const hectares = (field: Pick<Field, 'width_m' | 'length_m'>) =>
  (field.width_m * field.length_m) / 10_000
