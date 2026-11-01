"""Only convert already-delivered group centers to display RGB; do not classify."""
from unittest.mock import patch
import unittest
import cv2
from arm_bridge.colors import lab_display_colors


class LabDisplayTests(unittest.TestCase):
    def test_center_display_preserves_group_names_and_does_not_call_kmeans(self):
        with patch.object(cv2,'kmeans',side_effect=AssertionError('classification belongs to producer')):
            colors=lab_display_colors({'color_group_1':[0.,0.,0.],'color_group_2':[100.,0.,0.],'color_group_3':[50.,0.,0.]})
        self.assertEqual(set(colors),{'color_group_1','color_group_2','color_group_3'})
        for channel in colors['color_group_1']:self.assertAlmostEqual(channel,0.,places=3)
        for channel in colors['color_group_2']:self.assertAlmostEqual(channel,1.,places=3)
        self.assertLess(max(colors['color_group_3'])-min(colors['color_group_3']),.002)


if __name__=='__main__':unittest.main()
