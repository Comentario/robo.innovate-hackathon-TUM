"""Tiny synthetic contracts; no rendered sensor array is opened."""
import json
import unittest

import numpy as np

from evaluate import joint_decisions, scalar, score_stage, score_frame, summarize
from references import sample_returns


def reference():
    positive={"id":"brick_9_0_0","role":"exposed_top","polygon":[[1,1],[9,1],[9,17],[1,17]],
              "center_world_xy_m":[0.,0.],"yaw_world_rad":0.,"ridge_key":"L9_R0","long_index":0,
              "vertical_projection_uncovered":True}
    missing={"id":"brick_9_0_1","polygon":[[11,1],[19,1],[19,17],[11,17]],
             "center_world_xy_m":[.032,0.],"yaw_world_rad":0.,"ridge_key":"L9_R0","long_index":1,
             "left_anchor":"brick_9_0_0","right_anchor":"brick_9_0_2","classification":"observable_internal_absence"}
    return {"instances":[positive],"missing_references":[missing],"unknown_removed":[],
            "stack_roi_polygon":[[0,0],[30,0],[30,20],[0,20]],"current_layer":9,
            "body_top_world_m":.1,"stud_top_world_m":.1017,
            "current_yaw_world_rad":0.,
            "layer_heights":{"8":{"body_top_world_m":.0904,"stud_top_world_m":.0921},
                             "9":{"body_top_world_m":.1,"stud_top_world_m":.1017}}}


class Contracts(unittest.TestCase):
    def test_lower_height_does_not_hide_behind_correct_image_box(self):
        ref=reference();candidate={"id":"c","box_xyxy":[1,1,9,17],"decision":"present",
            "center_world_xy_m":[0.,0.],"yaw_world_rad":0.,"surface_height_world_m":.0904}
        result=score_stage([candidate],ref)
        self.assertEqual(result["matched"],1)
        self.assertEqual(result["height_consistent_reference_ids"],[])
        self.assertEqual(result["selected_lower_layer_ids"],["c"])

    def test_no_output_is_not_missing_success(self):
        result=joint_decisions([],reference())
        self.assertEqual(result["missing_decisions"]["no_match"],1)
        self.assertEqual(result["correct_missing"],0)

    def test_outside_image_scoring_still_has_lower_height_diagnostic(self):
        candidate={"id":"outside","box_xyxy":[40,1,48,17],"decision":"present","surface_height_world_m":.0904}
        result=score_stage([candidate],reference())
        self.assertEqual(result["outside_roi"],1)
        self.assertEqual(result["height_inconsistent_ids"],["outside"])
        self.assertEqual(result["selected_lower_layer_ids"],["outside"])

    def test_chain_and_band_reporting_from_existing_matches(self):
        candidate={"id":"c","box_xyxy":[1,1,9,17],"decision":"present","surface_height_world_m":.1,"parent_ridge_id":"p"}
        result=score_frame({"candidates":[candidate],"depth_direction":{"status":"supported","estimated_surface_height_world_m":.1}},reference())
        self.assertEqual(result["chain_stats"]["reference_ridges"],1)
        self.assertEqual(result["chain_stats"]["uncovered_reference_ridges"],[])
        self.assertEqual(result["band_diagnostic"]["classification"],"correct_current_layer")

    def test_missing_joint_assignment_and_wrong_missing(self):
        candidates=[{"id":"p","box_xyxy":[1,1,9,17],"decision":"missing","surface_height_world_m":.1},
                    {"id":"a","box_xyxy":[11,1,19,17],"decision":"missing","surface_height_world_m":.1}]
        result=joint_decisions(candidates,reference())
        self.assertEqual(result["known_missing_calls"],2)
        self.assertEqual(result["correct_missing"],1)
        self.assertEqual(result["wrong_missing_on_present"],1)
        candidates[1]["surface_height_world_m"]=.0904
        result=joint_decisions(candidates,reference())
        self.assertEqual(result["correct_missing"],0)
        self.assertEqual(result["wrong_height_missing_on_absence"],1)
        json.dumps(result,default=scalar)

    def test_invalid_depth_cannot_supply_lower_return_evidence(self):
        camera={"K":np.array([[100.,0,16],[0,100.,16],[0,0,1.]]),"R":np.diag([1.,-1.,-1.]),"eye":np.array([0.,0.,1.])}
        pixels=np.tile([[16.,16.]],(8,1));expected=np.full(8,.9)
        result=sample_returns(pixels,expected,np.full((32,32),np.nan),camera,.1)
        self.assertEqual(result["lower_return_samples"],0)
        result=sample_returns(pixels,expected,np.ones((32,32)),camera,.1)
        self.assertEqual(result["lower_return_samples"],8)


if __name__=="__main__":unittest.main()
