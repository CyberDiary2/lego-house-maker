"""Brick dimensions and footprint geometry.

Everything a design stores is in STUDS (horizontal) and COURSES (vertical).
Those are the units you actually think in when building with bricks, and they
are integers, so a design never accumulates floating point drift and two
designers always agree on what "12 wide" means.

The conversion to world units happens once, here, and must stay in step with
the LEGO_* constants in the game's own tools/build_scenes.gd.
"""

from __future__ import annotations

# 1 world unit = 30mm, which puts a soldier at roughly the size of the minifig
# these bricks are made for.
STUD = 0.267  # stud pitch, from Lego's real 8mm
COURSE = 0.32  # one brick course, from Lego's real 9.6mm
PLATE = 0.107  # one plate, a third of a course
WALL_STUDS = 2  # wall thickness; a standard brick is 2 studs deep

# Classic brick colours. Keys are what a design file stores.
COLOURS = {
    "red": (0.72, 0.13, 0.12),
    "blue": (0.09, 0.32, 0.62),
    "yellow": (0.94, 0.76, 0.09),
    "white": (0.92, 0.92, 0.90),
    "grey": (0.45, 0.47, 0.48),
    "lime": (0.32, 0.60, 0.20),
    "orange": (0.85, 0.44, 0.09),
    "sand": (0.83, 0.72, 0.51),
}

# A ramp shallow enough for the game's navmesh, which bakes with a 45 degree
# slope limit. Bots cannot jump at all, so anything steeper than this is a wall
# to them and any floor it serves is one they can never reach.
MAX_RAMP_DEGREES = 26.0


def studs_to_units(studs: float) -> float:
    """Horizontal distance in studs -> world units."""
    return studs * STUD


def courses_to_units(courses: float) -> float:
    """Vertical distance in brick courses -> world units."""
    return courses * COURSE


def ramp_run_studs(rise_courses: int) -> int:
    """How far a ramp must travel horizontally to climb `rise_courses`.

    Rounded UP to a whole stud so the ramp always lands on the grid, and so the
    real slope is never steeper than MAX_RAMP_DEGREES (rounding down would make
    it steeper, which is the direction that breaks bot pathing).
    """
    import math

    rise_units = courses_to_units(rise_courses)
    run_units = rise_units / math.tan(math.radians(MAX_RAMP_DEGREES))
    return math.ceil(run_units / STUD)


def edges(footprint: list[tuple[int, int]]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """The closed polygon's edges, in order. Edge i is wall i."""
    if len(footprint) < 3:
        return []
    return [
        (footprint[i], footprint[(i + 1) % len(footprint)])
        for i in range(len(footprint))
    ]


def edge_length_studs(edge: tuple[tuple[int, int], tuple[int, int]]) -> int:
    """Length of one wall in studs. Rectilinear, so exactly one axis varies."""
    (x1, y1), (x2, y2) = edge
    return abs(x2 - x1) + abs(y2 - y1)


def is_rectilinear(footprint: list[tuple[int, int]]) -> bool:
    """True when every edge runs along X or along Y, with no zero-length edges.

    Diagonal walls are rejected rather than approximated: bricks do not step
    diagonally without either a staircase of tiny offsets or stretched geometry,
    and both look wrong and confuse the navmesh.
    """
    if len(footprint) < 4:
        return False
    for (x1, y1), (x2, y2) in edges(footprint):
        if x1 != x2 and y1 != y2:
            return False
        if x1 == x2 and y1 == y2:
            return False
    return True


def signed_area(footprint: list[tuple[int, int]]) -> float:
    """Shoelace area in square studs. Sign tells you the winding direction."""
    total = 0.0
    for (x1, y1), (x2, y2) in edges(footprint):
        total += x1 * y2 - x2 * y1
    return total / 2.0


def bounds(footprint: list[tuple[int, int]]) -> tuple[int, int, int, int]:
    """(min_x, min_y, max_x, max_y) in studs."""
    xs = [p[0] for p in footprint]
    ys = [p[1] for p in footprint]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_footprint(footprint: list[tuple[int, int]], x: float, y: float) -> bool:
    """Ray casting, used to keep interior walls and ramps inside the building."""
    inside = False
    for (x1, y1), (x2, y2) in edges(footprint):
        if (y1 > y) != (y2 > y):
            cross_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < cross_x:
                inside = not inside
    return inside
