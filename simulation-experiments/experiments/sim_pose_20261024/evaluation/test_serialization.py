"""Tiny regression for result serialization; no images or inference."""
import json
import unittest

import numpy as np

from evaluate import json_scalar


class ScalarSerialization(unittest.TestCase):
    def test_numpy_counter_and_flags_preserve_values(self):
        result = {"fit_count": sum([np.bool_(True), np.bool_(False)]),
                  "valid": np.bool_(False), "error": np.float32(.5)}
        self.assertEqual(json.loads(json.dumps(result, default=json_scalar)),
                         {"fit_count": 1, "valid": False, "error": .5})

    def test_unexpected_array_is_still_rejected(self):
        with self.assertRaises(TypeError):
            json.dumps({"unexpected": np.array([1, 2])}, default=json_scalar)


if __name__ == "__main__":
    unittest.main()
