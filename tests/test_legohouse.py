"""Tests for the design model, geometry and wall splitting.

Stdlib unittest so `python -m unittest` works with nothing installed. The GUI is
not covered -- it needs a display -- but everything it edits is.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from legohouse import geometry as geo
from legohouse.model import Design, Storey, Opening, InteriorWall, Ramp
from legohouse.preview import _wall_segments

SQUARE = [(0, 0), (70, 0), (70, 56), (0, 56)]
ELL = [(0, 0), (60, 0), (60, 40), (30, 40), (30, 60), (0, 60)]


class TestGeometry(unittest.TestCase):
    def test_square_is_rectilinear(self):
        self.assertTrue(geo.is_rectilinear(SQUARE))

    def test_l_shape_is_rectilinear(self):
        self.assertTrue(geo.is_rectilinear(ELL))

    def test_diagonal_is_rejected(self):
        self.assertFalse(geo.is_rectilinear([(0, 0), (10, 5), (20, 0), (10, -5)]))

    def test_zero_length_wall_is_rejected(self):
        self.assertFalse(geo.is_rectilinear([(0, 0), (0, 0), (10, 0), (10, 10)]))

    def test_wall_count_matches_corner_count(self):
        self.assertEqual(len(geo.edges(ELL)), len(ELL))

    def test_edge_lengths(self):
        self.assertEqual(geo.edge_length_studs(((0, 0), (70, 0))), 70)
        self.assertEqual(geo.edge_length_studs(((0, 0), (0, 56))), 56)

    def test_ramp_run_is_never_steeper_than_the_limit(self):
        import math
        for courses in range(1, 25):
            run = geo.ramp_run_studs(courses)
            rise = geo.courses_to_units(courses)
            angle = math.degrees(math.atan2(rise, geo.studs_to_units(run)))
            self.assertLessEqual(
                angle, geo.MAX_RAMP_DEGREES + 1e-9,
                f"{courses} courses gives a {angle:.2f} degree ramp",
            )

    def test_point_in_footprint(self):
        self.assertTrue(geo.point_in_footprint(SQUARE, 35, 28))
        self.assertFalse(geo.point_in_footprint(SQUARE, -5, 28))
        # inside the L's bounding box but outside the L itself
        self.assertFalse(geo.point_in_footprint(ELL, 50, 50))


class TestValidation(unittest.TestCase):
    def base(self, storeys=1):
        return Design(footprint=list(SQUARE),
                      storeys=[Storey(wall_courses=10) for _ in range(storeys)])

    def test_clean_design_has_no_problems(self):
        self.assertEqual(self.base().validate(), [])

    def test_no_footprint_is_reported(self):
        self.assertTrue(any("footprint" in p for p in Design().validate()))

    def test_opening_past_the_end_of_its_wall(self):
        d = self.base()
        d.storeys[0].openings.append(
            Opening(kind="door", wall=0, from_studs=65, width_studs=12, height_courses=8))
        self.assertTrue(any("only 70 studs long" in p for p in d.validate()))

    def test_opening_on_a_wall_that_does_not_exist(self):
        d = self.base()
        d.storeys[0].openings.append(
            Opening(kind="door", wall=9, from_studs=0, width_studs=4, height_courses=8))
        self.assertTrue(any("does not exist" in p for p in d.validate()))

    def test_opening_taller_than_its_wall(self):
        d = self.base()
        d.storeys[0].openings.append(
            Opening(kind="window", wall=0, from_studs=0, width_studs=8,
                    sill_courses=8, height_courses=8))
        self.assertTrue(any("10-course wall" in p for p in d.validate()))

    def test_diagonal_interior_wall(self):
        d = self.base()
        d.storeys[0].interior_walls.append(InteriorWall(a=(5, 5), b=(20, 20)))
        self.assertTrue(any("diagonally" in p for p in d.validate()))

    def test_upper_storey_without_a_ramp_is_flagged(self):
        d = self.base(storeys=2)
        problems = d.validate()
        self.assertTrue(any("bots can never reach" in p for p in problems))

    def test_ramp_satisfies_the_upper_storey_warning(self):
        d = self.base(storeys=2)
        d.storeys[0].ramps.append(Ramp(at=(10, 50), direction="n"))
        self.assertEqual(d.validate(), [])

    def test_ramp_running_off_the_edge_is_reported(self):
        d = self.base(storeys=2)
        # 1 stud from the north wall, climbing north: nowhere near enough run
        d.storeys[0].ramps.append(Ramp(at=(10, 1), direction="n"))
        self.assertTrue(any("outside the building" in p for p in d.validate()))

    def test_ramp_on_the_top_storey_leads_nowhere(self):
        d = self.base()
        d.storeys[0].ramps.append(Ramp(at=(10, 50), direction="n"))
        self.assertTrue(any("leads nowhere" in p for p in d.validate()))

    def test_unknown_colour(self):
        d = self.base()
        d.colour = "chartreuse"
        self.assertTrue(any("unknown colour" in p for p in d.validate()))


class TestSerialisation(unittest.TestCase):
    def test_round_trip_preserves_everything(self):
        d = Design(name="round", colour="blue", roof=False, footprint=list(ELL),
                   storeys=[Storey(wall_courses=12), Storey(wall_courses=8)])
        d.storeys[0].openings.append(
            Opening(kind="window", wall=1, from_studs=4, width_studs=8,
                    sill_courses=4, height_courses=4))
        d.storeys[0].interior_walls.append(InteriorWall(a=(10, 0), b=(10, 40)))
        d.storeys[0].ramps.append(Ramp(at=(20, 35), direction="n", width_studs=10))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.json"
            d.save(path)
            back = Design.load(path)
        self.assertEqual(back.name, "round")
        self.assertEqual(back.colour, "blue")
        self.assertFalse(back.roof)
        self.assertEqual(back.footprint, ELL)
        self.assertEqual(len(back.storeys), 2)
        self.assertEqual(back.storeys[0].openings[0].sill_courses, 4)
        self.assertEqual(back.storeys[0].interior_walls[0].b, (10, 40))
        self.assertEqual(back.storeys[0].ramps[0].direction, "n")
        self.assertEqual(back.storeys[0].ramps[0].width_studs, 10)

    def test_future_schema_is_refused_rather_than_guessed_at(self):
        with self.assertRaises(ValueError):
            Design.from_dict({"schema": 999})

    def test_saved_file_is_readable_json(self):
        d = Design(footprint=list(SQUARE))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "d.json"
            d.save(path)
            data = json.loads(path.read_text())
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["footprint"][1], [70, 0])


class TestWallSegments(unittest.TestCase):
    """The wall is split around openings; these are what the game will build."""

    def test_solid_wall_is_one_run(self):
        d = Design(footprint=list(SQUARE))
        segs = list(_wall_segments(d, 0, 0))
        self.assertEqual(segs, [(0, 70, 0, 10)])

    def test_door_splits_the_wall_and_leaves_a_lintel(self):
        d = Design(footprint=list(SQUARE))
        d.storeys[0].openings.append(
            Opening(kind="door", wall=0, from_studs=30, width_studs=12, height_courses=8))
        segs = list(_wall_segments(d, 0, 0))
        self.assertIn((0, 30, 0, 10), segs)     # left of the door
        self.assertIn((30, 42, 8, 10), segs)    # lintel above it
        self.assertIn((42, 70, 0, 10), segs)    # right of the door
        # nothing spans the doorway at floor level
        self.assertFalse(any(a <= 30 and b >= 42 and lo == 0 for a, b, lo, _ in segs))

    def test_window_leaves_wall_below_and_above(self):
        d = Design(footprint=list(SQUARE))
        d.storeys[0].openings.append(
            Opening(kind="window", wall=0, from_studs=20, width_studs=8,
                    sill_courses=4, height_courses=4))
        segs = list(_wall_segments(d, 0, 0))
        self.assertIn((20, 28, 0, 4), segs)   # under the sill
        self.assertIn((20, 28, 8, 10), segs)  # over the head

    def test_full_height_door_leaves_no_lintel(self):
        d = Design(footprint=list(SQUARE))
        d.storeys[0].openings.append(
            Opening(kind="door", wall=0, from_studs=0, width_studs=70, height_courses=10))
        self.assertEqual(list(_wall_segments(d, 0, 0)), [])


if __name__ == "__main__":
    unittest.main()


class TestLayout(unittest.TestCase):
    """The site plan's own maths: rotation and what gets written out."""

    def setUp(self):
        from legohouse.layout import rotated_extent
        self.rotated_extent = rotated_extent
        self.design = Design(footprint=[(0, 0), (80, 0), (80, 40), (0, 40)])

    def test_rotation_swaps_the_axes_at_90_and_270(self):
        self.assertEqual(self.rotated_extent(self.design, 0), (80, 40))
        self.assertEqual(self.rotated_extent(self.design, 90), (40, 80))
        self.assertEqual(self.rotated_extent(self.design, 180), (80, 40))
        self.assertEqual(self.rotated_extent(self.design, 270), (40, 80))

    def test_plate_half_matches_the_maps_120_unit_half_extent(self):
        from legohouse.layout import PLATE_HALF_STUDS
        self.assertAlmostEqual(PLATE_HALF_STUDS * geo.STUD, 120.0, delta=0.5)

    def test_layout_round_trips_through_json(self):
        entries = [
            {"design": "cottage.json", "at_studs": [-140, -90], "rotation": 0},
            {"design": "corner_block.json", "at_studs": [220, 160], "rotation": 90},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseplate.json"
            path.write_text(json.dumps({"map": "baseplate", "buildings": entries}, indent=2))
            back = json.loads(path.read_text())["buildings"]
        self.assertEqual(back, entries)

    def test_rotation_only_ever_takes_the_four_legal_values(self):
        from legohouse.layout import ROTATIONS
        self.assertEqual(ROTATIONS, [0, 90, 180, 270])
