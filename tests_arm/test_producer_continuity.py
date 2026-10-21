"""Reference scene activation retains the producer handoff as well as geometry."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from arm_bridge.adapter import MoveItAdapter
from arm_bridge.scene_state import scene_digest


class ProducerContinuityTests(unittest.TestCase):
    def test_changed_or_dropped_handoff_is_refused_before_scene_access(self):
        parent={'person1_handoff':{'inventory_sha256':'producer-token','additional_score_filter':False}}
        harness=SimpleNamespace(job=parent)
        for job in ({},{'person1_handoff':{'inventory_sha256':'changed'}}):
            with self.assertRaisesRegex(ValueError,'producer handoff changed'):
                MoveItAdapter.verify_recovery_scene(harness,{}, {},{'job':job})
            with self.assertRaisesRegex(ValueError,'producer handoff changed'):
                MoveItAdapter.activate_recovery(harness,job,{})

    def test_activation_keeps_received_palette_and_marks_prefix_preserved(self):
        handoff={'inventory_sha256':'producer-token'}
        palette={'color_group_1':[.8,.7,.6],'color_group_2':[.9,.8,.7]}
        scene={};published=[]
        harness=SimpleNamespace(job={'person1_handoff':handoff},group_colors=deepcopy(palette),capture_scene=lambda:(None,scene),publish_state=lambda:published.append(True))
        job={'person1_handoff':handoff,'preserved_placements':[{'brick_id':'brick_001'}]}
        MoveItAdapter.activate_recovery(harness,job,{'scene_digest':scene_digest(scene)})
        self.assertEqual(harness.group_colors,palette)
        self.assertEqual(harness.placed,{'brick_001'})
        self.assertEqual(harness.job['person1_handoff'],handoff)
        self.assertEqual(published,[True])


if __name__=='__main__':unittest.main()
