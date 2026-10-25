import unittest,math
from greenfield.junctions import curve,length,at
class JunctionPaths(unittest.TestCase):
    def test_tangent_and_continuity(self):
        for a,b,reach in [([9,1.2845,0],[10.8,1.2845,-2/math.pi],.72),([23.2,1.2845,-2/math.pi],[24.25,1.2845,-.95],.38)]:
            p=curve(a,b,reach)
            self.assertEqual(p[0][:3],a);self.assertEqual(p[-1][:3],b)
            self.assertAlmostEqual(p[0][3],0);self.assertAlmostEqual(p[-1][3],0)
            self.assertGreater(length(p),math.dist(a,b))
            self.assertTrue(all(x[0]<y[0] for x,y in zip(p,p[1:])))
            self.assertEqual(at(p,0),p[0]);self.assertEqual(at(p,1),p[-1])
