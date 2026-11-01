"""Small CPU-only checks of task contracts and native grid conventions."""
import math
import unittest
from pathlib import Path

from challenge2.layout import Brick, SortPlan, connection_offset, exposed, load_config, overlaps, supports

CONFIG = Path(__file__).resolve().parents[1] / "configs/workcell.json"


class LayoutTests(unittest.TestCase):
    def test_removal_never_selects_a_covered_brick(self):
        plan = SortPlan(load_config(CONFIG))
        count = len(plan.remaining)
        while plan.target:
            target = plan.target
            self.assertIn(target, exposed(plan.remaining))
            self.assertFalse(any(t.layer > target.layer and overlaps(target, t) for t in plan.remaining))
            plan.complete(target)
        self.assertEqual(count, len(plan.completed))

    def test_rejects_never_enter_output_and_every_good_brick_does(self):
        cfg = load_config(CONFIG)
        plan = SortPlan(cfg)
        good = sum(b.color not in cfg["reject_colors"] for b in plan.remaining)
        while plan.target:
            plan.complete(plan.target)
        output = [b for slots in plan.placed.values() for b in slots]
        self.assertEqual(len(output), good)
        self.assertTrue(all(b.color not in cfg["reject_colors"] for b in output))

    def test_single_shade_separates_all_accepted_labels(self):
        cfg = load_config(CONFIG)
        cfg["recipe"] = "single_shade"
        plan = SortPlan(cfg)
        while plan.target:
            plan.complete(plan.target)
        self.assertEqual(set(plan.placed), set(cfg["colors"])-set(cfg["reject_colors"]))
        for color, slots in plan.placed.items():
            self.assertTrue(all(b.color == color for b in slots))

    def test_output_slots_have_support_and_no_same_layer_overlap(self):
        plan = SortPlan(load_config(CONFIG))
        while plan.target:
            plan.complete(plan.target)
        for slots in plan.placed.values():
            for i, b in enumerate(slots):
                self.assertTrue(b.layer == 0 or supports(slots[:i], b))
                self.assertFalse(any(a.layer == b.layer and overlaps(a, b) for a in slots[:i]))

    def test_native_offset_reconstructs_world_centers_for_all_supports(self):
        cfg = load_config(CONFIG)
        bricks = SortPlan(cfg).remaining
        for upper in bricks:
            for lower in supports(bricks, upper) if upper.layer else [None]:
                offset, yaw = connection_offset(lower, upper, cfg["baseplate_studs"])
                # Independently reconstruct interface corner positions in stud units.
                lq = 0 if lower is None else lower.yaw
                lcenter = (12, 12) if lower is None else (lower.x+lower.footprint[0]/2, lower.y+lower.footprint[1]/2)
                lhalf = (12, 12) if lower is None else (2, 1)
                ucenter = (upper.x+upper.footprint[0]/2, upper.y+upper.footprint[1]/2)
                def rotate(v, q):
                    return (v[0], v[1]) if q == 0 else (-v[1], v[0])
                lc = rotate((-lhalf[0], -lhalf[1]), lq)
                uc = rotate((-2, -1), upper.yaw)
                translated = rotate(offset, lq)
                for axis in (0, 1):
                    self.assertAlmostEqual(lcenter[axis]+lc[axis]+translated[axis], ucenter[axis]+uc[axis])
                self.assertEqual(yaw, (upper.yaw-lq)%4)

    def test_pose_is_meters_bottom_center_and_wxyz(self):
        b = Brick("test", 10, 10, 2, 1, "tan")
        pos, quat = b.pose((0.45, 0.16), 24)
        self.assertAlmostEqual(pos[0], 0.442)
        self.assertAlmostEqual(pos[1], 0.16)
        self.assertAlmostEqual(pos[2], 0.0224)
        self.assertAlmostEqual(sum(v*v for v in quat), 1)
        self.assertAlmostEqual(quat[0], math.sqrt(0.5))


if __name__ == "__main__":
    unittest.main()
