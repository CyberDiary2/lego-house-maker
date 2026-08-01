"""Optional 3D preview of a design, drawn with matplotlib.

Deliberately optional and deliberately crude: it exists to answer "is this the
shape I meant, and are the openings where I think" before committing a design to
the game, not to look like the game. The game itself is the real preview.

matplotlib is imported inside the functions so the editor still runs, minus this
button, on a machine that does not have it.
"""

from __future__ import annotations

from . import geometry as geo
from .model import Design

WALL_T = geo.WALL_STUDS  # wall thickness, in studs


def _wall_segments(design: Design, storey_index: int, wall_index: int):
    """The solid runs of one wall, split around its openings.

    Yields (start_stud, end_stud, bottom_course, top_course) pieces. A door
    leaves a full-height gap; a window leaves the wall below its sill and above
    its head, which is what makes a window read as a window from inside.
    """
    storey = design.storeys[storey_index]
    walls = geo.edges(design.footprint)
    span = geo.edge_length_studs(walls[wall_index])
    height = storey.wall_courses
    openings = sorted(
        [o for o in storey.openings if o.wall == wall_index],
        key=lambda o: o.from_studs,
    )
    cursor = 0
    for opening in openings:
        if opening.from_studs > cursor:
            yield (cursor, opening.from_studs, 0, height)
        if opening.kind == "window":
            # the wall survives under the sill and over the head
            if opening.sill_courses > 0:
                yield (opening.from_studs, opening.from_studs + opening.width_studs,
                       0, opening.sill_courses)
            head = opening.sill_courses + opening.height_courses
            if head < height:
                yield (opening.from_studs, opening.from_studs + opening.width_studs,
                       head, height)
        else:
            head = opening.height_courses
            if head < height:
                yield (opening.from_studs, opening.from_studs + opening.width_studs,
                       head, height)
        cursor = max(cursor, opening.from_studs + opening.width_studs)
    if cursor < span:
        yield (cursor, span, 0, height)


def build_faces(design: Design):
    """Every quad to draw, as (list of 4 xyz points, colour)."""
    faces = []
    colour = geo.COLOURS.get(design.colour, (0.7, 0.7, 0.7))
    trim = (0.92, 0.92, 0.90)
    walls = geo.edges(design.footprint)
    base_course = 0
    for storey_index, storey in enumerate(design.storeys):
        for wall_index, ((x1, y1), (x2, y2)) in enumerate(walls):
            span = geo.edge_length_studs(((x1, y1), (x2, y2)))
            if span == 0:
                continue
            ux, uy = (x2 - x1) / span, (y2 - y1) / span
            for a, b, lo, hi in _wall_segments(design, storey_index, wall_index):
                ax, ay = x1 + ux * a, y1 + uy * a
                bx, by = x1 + ux * b, y1 + uy * b
                z0 = geo.courses_to_units(base_course + lo)
                z1 = geo.courses_to_units(base_course + hi)
                faces.append((
                    [(geo.studs_to_units(ax), geo.studs_to_units(ay), z0),
                     (geo.studs_to_units(bx), geo.studs_to_units(by), z0),
                     (geo.studs_to_units(bx), geo.studs_to_units(by), z1),
                     (geo.studs_to_units(ax), geo.studs_to_units(ay), z1)],
                    colour,
                ))
        for wall in storey.interior_walls:
            z0 = geo.courses_to_units(base_course)
            z1 = geo.courses_to_units(base_course + storey.wall_courses)
            faces.append((
                [(geo.studs_to_units(wall.a[0]), geo.studs_to_units(wall.a[1]), z0),
                 (geo.studs_to_units(wall.b[0]), geo.studs_to_units(wall.b[1]), z0),
                 (geo.studs_to_units(wall.b[0]), geo.studs_to_units(wall.b[1]), z1),
                 (geo.studs_to_units(wall.a[0]), geo.studs_to_units(wall.a[1]), z1)],
                trim,
            ))
        for ramp in storey.ramps:
            run = geo.ramp_run_studs(storey.wall_courses)
            dx, dy = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}[ramp.direction]
            # across the ramp, perpendicular to the way it climbs
            px, py = (-dy, dx)
            half = ramp.width_studs / 2.0
            foot = (ramp.at[0], ramp.at[1])
            tip = (ramp.at[0] + dx * run, ramp.at[1] + dy * run)
            z0 = geo.courses_to_units(base_course)
            z1 = geo.courses_to_units(base_course + storey.wall_courses)
            faces.append((
                [(geo.studs_to_units(foot[0] + px * half), geo.studs_to_units(foot[1] + py * half), z0),
                 (geo.studs_to_units(foot[0] - px * half), geo.studs_to_units(foot[1] - py * half), z0),
                 (geo.studs_to_units(tip[0] - px * half), geo.studs_to_units(tip[1] - py * half), z1),
                 (geo.studs_to_units(tip[0] + px * half), geo.studs_to_units(tip[1] + py * half), z1)],
                (0.69, 0.44, 0.82),
            ))
        base_course += storey.wall_courses
    if design.roof and design.footprint:
        z = geo.courses_to_units(base_course)
        faces.append((
            [(geo.studs_to_units(x), geo.studs_to_units(y), z) for x, y in design.footprint],
            colour,
        ))
    return faces


def render(design: Design, out_path: str | None = None):
    """Draw the design. Saves to `out_path` if given, else opens a window."""
    import matplotlib
    if out_path:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    faces = build_faces(design)
    fig = plt.figure(figsize=(9, 7))
    ax = fig.add_subplot(111, projection="3d")
    if faces:
        ax.add_collection3d(Poly3DCollection(
            [f[0] for f in faces],
            facecolors=[f[1] for f in faces],
            edgecolors=(0.1, 0.1, 0.1, 0.5),
            linewidths=0.4,
        ))
        xs = [p[0] for f in faces for p in f[0]]
        ys = [p[1] for f in faces for p in f[0]]
        zs = [p[2] for f in faces for p in f[0]]
        span = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs), 1.0)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        ax.set_xlim(cx - span / 2, cx + span / 2)
        ax.set_ylim(cy - span / 2, cy + span / 2)
        ax.set_zlim(0, span)
    ax.set_xlabel("x (units)")
    ax.set_ylabel("z (units)")
    ax.set_zlabel("height")
    ax.set_title(f"{design.name}  |  {design.colour}  |  {len(design.storeys)} storey(s)")
    ax.view_init(elev=24, azim=-125)
    if out_path:
        fig.savefig(out_path, dpi=110, bbox_inches="tight")
        plt.close(fig)
        return out_path
    plt.show()
    return None


def show_preview(design: Design) -> None:
    render(design)
