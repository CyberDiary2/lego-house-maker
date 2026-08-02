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


def _boundary_crossings(footprint, axis: str, fixed: int) -> list[float]:
    """Where a line crosses the footprint boundary, sorted along the line.

    The line runs parallel to `axis` ("x" or "y") with its other coordinate held
    at `fixed`. For a rectilinear footprint the returned coordinates pair up into
    alternating inside/outside spans: (xs[0], xs[1]) is inside, (xs[1], xs[2]) is
    outside, and so on -- the same even-odd rule point_in_footprint() uses.
    """
    xs: list[float] = []
    for (x1, y1), (x2, y2) in edges(footprint):
        if axis == "x":  # horizontal line at y == fixed; record the x it crosses at
            if (y1 > fixed) != (y2 > fixed):
                xs.append(x1 + (fixed - y1) * (x2 - x1) / (y2 - y1))
        else:            # vertical line at x == fixed; record the y it crosses at
            if (x1 > fixed) != (x2 > fixed):
                xs.append(y1 + (fixed - x1) * (y2 - y1) / (x2 - x1))
    xs.sort()
    return xs


def clip_interior_wall(footprint, a, b, inset: int | None = None):
    """Trim an axis-aligned interior wall so its ends land on the INNER FACE of
    the exterior walls, never running into them or straight through.

    Exterior walls are WALL_STUDS thick and centred on the footprint line, so the
    clear inside of a room is that line pulled in by WALL_STUDS // 2 studs. The
    wall is clamped to the room its middle sits in, and only ever shortened --
    never stretched past what was drawn. Returns the clamped ((x, y), (x, y)), or
    None when nothing of the wall lands inside a room (drawn in a wall or outside
    the building). A diagonal or zero-length segment is returned untouched, for
    InteriorWall.validate() to report.
    """
    if inset is None:
        inset = WALL_STUDS // 2
    (x1, y1), (x2, y2) = a, b
    if y1 == y2 and x1 != x2:
        axis, fixed, v0, v1 = "x", y1, x1, x2
    elif x1 == x2 and y1 != y2:
        axis, fixed, v0, v1 = "y", x1, y1, y2
    else:
        return (tuple(a), tuple(b))
    lo, hi = (v0, v1) if v0 <= v1 else (v1, v0)
    crossings = _boundary_crossings(footprint, axis, fixed)
    mid = (lo + hi) / 2.0
    room = None
    for i in range(0, len(crossings) - 1, 2):
        if crossings[i] <= mid <= crossings[i + 1]:
            room = (crossings[i], crossings[i + 1])
            break
    if room is None:
        return None
    new_lo = int(round(max(lo, room[0] + inset)))
    new_hi = int(round(min(hi, room[1] - inset)))
    if new_hi - new_lo < 1:  # the whole wall was inside the exterior wall band
        return None
    if axis == "x":
        return ((new_lo, fixed), (new_hi, fixed))
    return ((fixed, new_lo), (fixed, new_hi))


# --- recommended sizes -------------------------------------------------------
# What "normal" looks like, so the editor can show it next to each control and
# you are not guessing at numbers with no reference. These are the values the
# game's own hand-built buildings use, and a soldier is 1.8 world units tall
# (about 7 brick courses), which is what makes them feel right.
DEFAULTS = {
    "wall_courses": 10,      # one storey; 3.2 units, comfortable headroom
    "storeys": 2,
    "door_width_studs": 12,
    "door_height_courses": 8,
    "window_width_studs": 8,
    "window_sill_courses": 4,
    "window_height_courses": 4,
    "ramp_width_studs": 12,
    "building_width_studs": 70,
    "building_depth_studs": 56,
}

# Shown under the matching control. Kept as prose rather than bare numbers
# because the useful part is usually WHY, not the value.
HINTS = {
    "wall_courses": "10 = one normal storey. 7 is head height on a soldier; "
                    "under that feels like a crawlspace. 20 makes a tall hall.",
    "door_width_studs": "12 studs is a normal doorway. Under 6 and soldiers "
                        "snag on the frame.",
    "window_sill_courses": "sill 4, height 4 puts a window at chest height on "
                           "a standing soldier.",
    "ramp_width_studs": "12 studs. Narrower still works, but bots path down "
                        "the middle and bunch up on it.",
    "footprint": "70 x 56 studs (about 19 x 15 units) is the size of the "
                 "buildings already in the game. Much under 40 x 40 and there "
                 "is no room inside for a ramp.",
    "storeys": "2 is typical. Every storey above the first needs a ramp under "
               "it or bots can never get up there.",
}
