"""Small scoring-contract tests; no image inference or batch computation."""
import unittest

from perception.evaluation.evaluate import point_errors, score_image


def polygon(x0, x1):
    return [[x0, 0], [x1, 0], [x1, 20], [x0, 20]]


class ScoringContractTests(unittest.TestCase):
    def reference(self):
        return {"file": "test.jpg", "correlation_group": "test", "studs": [], "instances": [
            {"id": "a", "polygon": polygon(0, 10), "orientation_deg": 90, "role": "exposed_top"},
            {"id": "b", "polygon": polygon(10, 20), "orientation_deg": 90, "role": "exposed_top"}]}

    def candidate(self, name, poly, decision):
        return {"id": name, "polygon": poly, "decision": decision, "layer_hypothesis": "top_compatible", "orientation_deg": 90, "studs": []}

    def test_uncertain_and_unmatched_do_not_count_as_correct_missing(self):
        ref = self.reference()
        absent = [{"reference_id": "missing", "polygon": polygon(30, 40)}]
        pred = {"candidates": [self.candidate("a", polygon(0, 10), "uncertain")]}
        scored = score_image(pred, ref, absent)
        self.assertEqual(scored["positive_decisions"], {"present": 0, "missing": 0, "uncertain": 1, "no_match": 1})
        self.assertEqual(scored["missing_decisions"]["no_match"], 1)
        self.assertEqual(scored["missing_decisions"]["missing"], 0)

    def test_wrong_present_on_absence_reduces_precision(self):
        ref = self.reference()
        absent = [{"reference_id": "missing", "polygon": polygon(30, 40)}]
        pred = {"candidates": [self.candidate("a", polygon(0, 10), "present"), self.candidate("m", polygon(30, 40), "present")]}
        scored = score_image(pred, ref, absent)
        self.assertEqual(scored["correct_present"], 1)
        self.assertEqual(scored["missing_decisions"]["present"], 1)
        self.assertEqual(scored["present_instance_precision"], .5)

    def test_merge_is_not_an_individual_match(self):
        scored = score_image({"candidates": [self.candidate("merge", polygon(0, 20), "present")]}, self.reference(), [])
        self.assertEqual(scored["merged_candidates"], 1)
        self.assertEqual(scored["correct_present"], 0)
        self.assertEqual(scored["missed_individual_faces"], 2)

    def test_correct_missing_is_explicit(self):
        absent = [{"reference_id": "missing", "polygon": polygon(30, 40)}]
        scored = score_image({"candidates": [self.candidate("missing", polygon(30, 40), "missing")]}, self.reference(), absent)
        self.assertEqual(scored["missing_decisions"]["missing"], 1)
        self.assertEqual(scored["missing_correct_coverage"], 1)

    def test_point_matching_never_accepts_outside_tolerance(self):
        self.assertEqual(point_errors([[0, 0]], [[20, 0]], max_distance=8), [])
        self.assertEqual(point_errors([[0, 0]], [[3, 4]], max_distance=8), [5.0])


if __name__ == "__main__":
    unittest.main()
