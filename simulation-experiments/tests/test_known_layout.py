"""Small non-intensive geometry/sanity checks; not a perception benchmark."""

import json
from pathlib import Path
import unittest

import numpy as np

from perception.algorithm import analyze


class KnownLayoutTests(unittest.TestCase):
    def test_blank_cannot_confirm_present_or_missing(self):
        root=Path(__file__).resolve().parents[1]
        # Tiny one-cell window is sufficient to exercise observability logic.
        registration={"file":"blank","canonical_quad_xy":[[20,20],[180,20],[180,180],[20,180]],
            "supplied_layout":{"strips":1,"groups_along_strip":1,"strip_pitch_studs":4}}
        for version in ("v0","v1"):
            with self.subTest(version=version):
                config=json.loads((root/f"perception/configs/baseline_{version}.json").read_text())
                result=analyze(np.full((200,200,3),128,np.uint8),registration,config)
                self.assertEqual(len(result["candidates"]),1)
                self.assertEqual(result["candidates"][0]["decision"],"uncertain")
                self.assertFalse(result["candidates"][0]["layer_verified"])
                self.assertTrue(result["registration"]["manual_assisted"])


if __name__=="__main__":
    unittest.main()
