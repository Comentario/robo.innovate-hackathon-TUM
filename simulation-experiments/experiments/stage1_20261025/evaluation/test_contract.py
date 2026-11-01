"""Tiny synthetic contracts; no image, depth or simulation batch."""
import copy
import unittest

import evaluate


class Contracts(unittest.TestCase):
    def test_metric_eligibility_is_not_raw_geometry_credit(self):
        candidate = {"id": "c", "center_world_xy_m": [.002, .002], "surface_height_world_m": .102, "yaw_world_rad": 0.}
        raw = {"candidates": [candidate]}
        row = {"present": {"matches": [{"detection_id": "c", "reference_id": "r"}],
                           "raw_detections": 1, "ambiguous_ignored": 0, "outside_roi": 0}}
        reference = {"body_top_world_m": .1, "stud_top_world_m": .1017,
                     "instances": [{"id": "r", "center_world_xy_m": [0., 0.], "yaw_world_rad": 0.}]}
        limits = {"xy_error_m_max": .003, "undirected_yaw_error_deg_max": 5., "surface_distance_to_body_or_stud_top_m_max": .003}
        self.assertEqual(evaluate.eligibility(raw, row, reference, limits)["eligible_reference_ids"], ["r"])
        candidate["surface_height_world_m"] = .08
        result = evaluate.eligibility(raw, row, reference, limits)
        self.assertEqual(result["eligible_reference_ids"], [])
        self.assertEqual(result["noneligible_or_unverified_present"], 1)

    def test_no_present_blocks_observed_mock_fixture_credit(self):
        spec = {"fixtures": {"good_selected": {"status": "joined", "destination": "main"}}, "guards": []}
        self.assertFalse(evaluate.mock_score({"fixtures": [], "guard_checks": []}, set(), spec)["passed"])

    def test_adapter_cannot_promote_or_move_a_candidate(self):
        raw_candidate = {"id": "c", "decision": "uncertain", "polygon": [[1., 2.]], "box_xyxy": [1., 2., 3., 4.],
                         "center_world_xy_m": [0., 0.], "surface_height_world_m": .1, "yaw_world_rad": 0.}
        payload = {"frame_id": "opaque0", "coordinate_frame": "table", "candidates": [
            {"candidate_id": "c", "decision": "uncertain", "image_polygon": [[1., 2.]], "box_xyxy": [1., 2., 3., 4.],
             "table_xy_m": [0., 0.], "estimated_body_top_from_selected_band_m": .1, "yaw_table_rad": 0.}]}
        evaluate.adapted({"candidates": [raw_candidate]}, payload, {"id": "opaque0"})
        altered = copy.deepcopy(payload); altered["candidates"][0]["decision"] = "present"
        with self.assertRaises(ValueError):
            evaluate.adapted({"candidates": [raw_candidate]}, altered, {"id": "opaque0"})


if __name__ == "__main__":
    unittest.main()
