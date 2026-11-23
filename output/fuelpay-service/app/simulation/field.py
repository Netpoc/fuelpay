"""Field geometry for mobile machinery.

A field is an oriented rectangle: a centre, a length along a compass heading
and a width across it. Working passes run along the length, back and forth
across the width (a boustrophedon), leaving a headland at each end where the
machine turns.

Coordinates are handled in a local flat frame, metres east and north of the
field centre. At field scale (≤ 1.5 km) the error of treating the Earth as flat
is far below GPS noise. Field-relative positions are (along, across): metres
along the long axis from the centre, and metres to the right of it.

Pure: no I/O, no randomness.
"""

import math
from dataclasses import dataclass

METRES_PER_DEGREE_LAT = 111_320.0
EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class FieldGeometry:
    latitude: float
    longitude: float
    width_m: float
    length_m: float
    # Bearing of the long axis, degrees clockwise from north.
    heading_deg: float = 0.0


def _cos_lat(latitude: float) -> float:
    # Guard the pole singularity where cos(lat) collapses to zero.
    return max(math.cos(math.radians(latitude)), 1e-6)


def offset_latlon(
    latitude: float, longitude: float, east_m: float, north_m: float
) -> tuple[float, float]:
    """The point `east_m`/`north_m` from an origin, as (lat, lon)."""
    lat = latitude + north_m / METRES_PER_DEGREE_LAT
    lon = longitude + east_m / (METRES_PER_DEGREE_LAT * _cos_lat(latitude))
    return lat, lon


def local_offset(
    origin_lat: float, origin_lon: float, latitude: float, longitude: float
) -> tuple[float, float]:
    """Inverse of `offset_latlon`: (east_m, north_m) of a point from an origin."""
    north = (latitude - origin_lat) * METRES_PER_DEGREE_LAT
    east = (longitude - origin_lon) * METRES_PER_DEGREE_LAT * _cos_lat(origin_lat)
    return east, north


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing from the first point to the second, 0-360."""
    east, north = local_offset(lat1, lon1, lat2, lon2)
    return math.degrees(math.atan2(east, north)) % 360.0


def _axes(heading_deg: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """Unit vectors (east, north) along the long axis and across it (to the right)."""
    h = math.radians(heading_deg)
    along = (math.sin(h), math.cos(h))
    across = (math.cos(h), -math.sin(h))
    return along, across


def field_to_latlon(field: FieldGeometry, along_m: float, across_m: float) -> tuple[float, float]:
    """Field-relative position to (lat, lon)."""
    (ae, an), (ce, cn) = _axes(field.heading_deg)
    east = along_m * ae + across_m * ce
    north = along_m * an + across_m * cn
    return offset_latlon(field.latitude, field.longitude, east, north)


def latlon_to_field(field: FieldGeometry, latitude: float, longitude: float) -> tuple[float, float]:
    """(lat, lon) to field-relative (along, across)."""
    east, north = local_offset(field.latitude, field.longitude, latitude, longitude)
    (ae, an), (ce, cn) = _axes(field.heading_deg)
    return east * ae + north * an, east * ce + north * cn


def contains(
    field: FieldGeometry, latitude: float, longitude: float, margin_m: float = 0.0
) -> bool:
    """Whether a point lies inside the field, optionally widened by `margin_m`."""
    along, across = latlon_to_field(field, latitude, longitude)
    return (
        abs(along) <= field.length_m / 2 + margin_m and abs(across) <= field.width_m / 2 + margin_m
    )


def field_polygon(field: FieldGeometry) -> list[tuple[float, float]]:
    """Corners as (lat, lon), closed ring (first point repeated last)."""
    half_l, half_w = field.length_m / 2, field.width_m / 2
    corners = [
        field_to_latlon(field, -half_l, -half_w),
        field_to_latlon(field, half_l, -half_w),
        field_to_latlon(field, half_l, half_w),
        field_to_latlon(field, -half_l, half_w),
    ]
    return [*corners, corners[0]]


def area_ha(field: FieldGeometry) -> float:
    return field.width_m * field.length_m / 10_000.0


@dataclass(frozen=True)
class Pass:
    """One working run along the field: from `start_along` to `end_along` at
    a fixed `across` offset. Direction alternates pass to pass."""

    across_m: float
    start_along_m: float
    end_along_m: float

    @property
    def length_m(self) -> float:
        return abs(self.end_along_m - self.start_along_m)


def boustrophedon_passes(
    field: FieldGeometry, implement_width_m: float, headland_m: float
) -> list[Pass]:
    """Lay out back-and-forth passes covering the field.

    Passes start half an implement width in from the side headland and step
    one implement width at a time, so adjacent passes abut without overlap.
    The headland at each end is left for turning, as on a real field.
    """
    if implement_width_m <= 0:
        raise ValueError("implement width must be positive")

    usable_width = field.width_m - 2 * headland_m
    half_run = field.length_m / 2 - headland_m
    if usable_width < implement_width_m or half_run <= 0:
        # A field too small for headlands is worked as a single straight run.
        return [
            Pass(across_m=0.0, start_along_m=-field.length_m / 2, end_along_m=field.length_m / 2)
        ]

    count = max(1, int(usable_width // implement_width_m))
    first = -usable_width / 2 + implement_width_m / 2
    passes: list[Pass] = []
    for index in range(count):
        across = first + index * implement_width_m
        if index % 2 == 0:
            passes.append(Pass(across, -half_run, half_run))
        else:
            passes.append(Pass(across, half_run, -half_run))
    return passes
