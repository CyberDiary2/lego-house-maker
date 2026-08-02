"""The design document: what a saved .json file contains, and its rules.

The shape deliberately echoes tinyhome.club's own design.json -- overall
dimensions, a wall height, and a list of openings each pinned to a wall with an
offset and a size -- with feet swapped for studs and courses, and with storeys
so a building can have more than one floor.

Everything is plain data. The game reads these files at build time and turns
them into bricks; nothing here knows about rendering.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from . import geometry as geo

SCHEMA_VERSION = 1


@dataclass
class Opening:
    """A door or window cut into one wall of one storey.

    `wall` indexes the footprint's edges, so wall 0 is the edge from footprint
    point 0 to point 1. `from_studs` is measured along that wall from its first
    point, which keeps an opening's position meaningful even if the building is
    later moved or the whole footprint is scaled.
    """

    kind: str  # "door" or "window"
    wall: int
    from_studs: int
    width_studs: int
    # windows only; a door always starts at the floor and its height is its own
    sill_courses: int = 0
    height_courses: int = 0

    def validate(self, design: "Design", storey_index: int) -> list[str]:
        problems: list[str] = []
        if self.kind not in ("door", "window"):
            problems.append(f"opening kind must be door or window, got {self.kind!r}")
        walls = geo.edges(design.footprint)
        if not 0 <= self.wall < len(walls):
            problems.append(f"opening on wall {self.wall}, which does not exist")
            return problems
        span = geo.edge_length_studs(walls[self.wall])
        if self.width_studs <= 0:
            problems.append("opening width must be at least 1 stud")
        if self.from_studs < 0 or self.from_studs + self.width_studs > span:
            problems.append(
                f"opening runs from {self.from_studs} to "
                f"{self.from_studs + self.width_studs} studs on wall {self.wall}, "
                f"which is only {span} studs long"
            )
        storey = design.storeys[storey_index]
        top = self.sill_courses + self.height_courses if self.kind == "window" else self.height_courses
        if top > storey.wall_courses:
            problems.append(
                f"opening reaches {top} courses on a {storey.wall_courses}-course wall"
            )
        return problems


@dataclass
class InteriorWall:
    """A dividing wall inside the footprint, as a single axis-aligned segment."""

    a: tuple[int, int]
    b: tuple[int, int]

    def validate(self, design: "Design", storey_index: int) -> list[str]:
        problems: list[str] = []
        (x1, y1), (x2, y2) = self.a, self.b
        if x1 != x2 and y1 != y2:
            problems.append("interior walls must run along X or Y, not diagonally")
        if (x1, y1) == (x2, y2):
            problems.append("interior wall has zero length")
        return problems


@dataclass
class Ramp:
    """A ramp from this storey up to the next.

    Ramps are what make upper floors usable by bots: the game's bots path purely
    on a baked navmesh and cannot jump, so a floor with no ramp serving it is a
    floor they will never reach, however easy it looks to a player.
    """

    at: tuple[int, int]  # foot of the ramp, in studs
    direction: str  # "n", "s", "e", "w" -- the way it climbs
    width_studs: int = 12

    def validate(self, design: "Design", storey_index: int) -> list[str]:
        problems: list[str] = []
        if self.direction not in ("n", "s", "e", "w"):
            problems.append(f"ramp direction must be n/s/e/w, got {self.direction!r}")
            return problems
        if self.width_studs <= 0:
            problems.append("ramp width must be at least 1 stud")
        storey = design.storeys[storey_index]
        run = geo.ramp_run_studs(storey.wall_courses)
        dx, dy = {"n": (0, -1), "s": (0, 1), "e": (1, 0), "w": (-1, 0)}[self.direction]
        top = (self.at[0] + dx * run, self.at[1] + dy * run)
        if not geo.point_in_footprint(design.footprint, top[0] + 0.5, top[1] + 0.5):
            problems.append(
                f"ramp from {self.at} climbing {self.direction} needs {run} studs of "
                f"run and would end at {top}, outside the building"
            )
        return problems


@dataclass
class Storey:
    """One floor: how tall its walls are, and everything placed on it."""

    wall_courses: int = 10
    openings: list[Opening] = field(default_factory=list)
    interior_walls: list[InteriorWall] = field(default_factory=list)
    ramps: list[Ramp] = field(default_factory=list)


@dataclass
class Design:
    """A whole building."""

    name: str = "untitled"
    colour: str = "red"
    roof: bool = True
    footprint: list[tuple[int, int]] = field(default_factory=list)
    storeys: list[Storey] = field(default_factory=lambda: [Storey()])

    # --- validation ------------------------------------------------------
    def validate(self) -> list[str]:
        """Every problem with this design, as plain sentences. Empty means good.

        Collects ALL problems rather than raising on the first, so the editor can
        show everything wrong at once instead of one thing per save attempt.
        """
        problems: list[str] = []
        if not self.footprint:
            problems.append("the building has no footprint yet")
        elif not geo.is_rectilinear(self.footprint):
            problems.append(
                "the footprint must be a closed rectilinear shape: at least 4 "
                "corners, every wall along X or Y, no zero-length walls"
            )
        if self.colour not in geo.COLOURS:
            problems.append(f"unknown colour {self.colour!r}")
        if not self.storeys:
            problems.append("a building needs at least one storey")
        for i, storey in enumerate(self.storeys):
            where = f"storey {i + 1}"
            if storey.wall_courses <= 0:
                problems.append(f"{where}: wall height must be at least 1 course")
            if self.footprint and geo.is_rectilinear(self.footprint):
                for opening in storey.openings:
                    problems += [f"{where}: {p}" for p in opening.validate(self, i)]
                for wall in storey.interior_walls:
                    problems += [f"{where}: {p}" for p in wall.validate(self, i)]
                # A ramp climbs to whatever sits above this storey: the next
                # floor, or -- on the top storey -- the roof, when the design has
                # one (the game cuts the roof slab open for it just as it does an
                # interior floor). Only a top-storey ramp with no roof above it
                # truly leads nowhere.
                if i < len(self.storeys) - 1 or self.roof:
                    for ramp in storey.ramps:
                        problems += [f"{where}: {p}" for p in ramp.validate(self, i)]
                elif storey.ramps:
                    problems.append(
                        f"{where}: has a ramp but is the top storey with no roof, so "
                        "it leads nowhere (add a roof or another storey above it)"
                    )
        # a building bots can enter but not climb is worth warning about
        for i, storey in enumerate(self.storeys[:-1]):
            if not storey.ramps:
                problems.append(
                    f"storey {i + 1}: no ramp up, so bots can never reach "
                    f"storey {i + 2} (they cannot jump)"
                )
        return problems

    # --- serialisation ---------------------------------------------------
    def to_dict(self) -> dict:
        data = asdict(self)
        data["schema"] = SCHEMA_VERSION
        # tuples become lists in JSON anyway; be explicit so round trips match
        data["footprint"] = [[int(x), int(y)] for x, y in self.footprint]
        for storey in data["storeys"]:
            for wall in storey["interior_walls"]:
                wall["a"] = [int(v) for v in wall["a"]]
                wall["b"] = [int(v) for v in wall["b"]]
            for ramp in storey["ramps"]:
                ramp["at"] = [int(v) for v in ramp["at"]]
        return data

    @staticmethod
    def from_dict(data: dict) -> "Design":
        version = data.get("schema", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"design uses schema {version}, this build understands "
                f"{SCHEMA_VERSION}"
            )
        storeys = []
        for raw in data.get("storeys", []):
            storeys.append(
                Storey(
                    wall_courses=int(raw.get("wall_courses", 10)),
                    openings=[Opening(**o) for o in raw.get("openings", [])],
                    interior_walls=[
                        InteriorWall(a=tuple(w["a"]), b=tuple(w["b"]))
                        for w in raw.get("interior_walls", [])
                    ],
                    ramps=[
                        Ramp(
                            at=tuple(r["at"]),
                            direction=r["direction"],
                            width_studs=int(r.get("width_studs", 12)),
                        )
                        for r in raw.get("ramps", [])
                    ],
                )
            )
        return Design(
            name=data.get("name", "untitled"),
            colour=data.get("colour", "red"),
            roof=bool(data.get("roof", True)),
            footprint=[tuple(p) for p in data.get("footprint", [])],
            storeys=storeys or [Storey()],
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n")

    @staticmethod
    def load(path: str | Path) -> "Design":
        return Design.from_dict(json.loads(Path(path).read_text()))
