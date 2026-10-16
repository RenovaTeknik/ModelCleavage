import sys,pathlib,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
import manifold3d as mf
from cutting_engine.interface import interface_sweep
from cutting_engine.model import interface_direction
class StarterRegressions(unittest.TestCase):
    def test_edge_on_surface_is_included_in_directional_sweep(self):
        painted=np.array([[[0,0,1],[1,0,1],[0,1,1]],[[2,0,0],[2,1,0],[2,0,2]]],float)
        solid,details=interface_sweep(painted,np.array([0.,0.,1.]),1)
        probe=mf.Manifold.cube([.002,.002,.002]).translate([1.999,.249,.499])
        self.assertAlmostEqual((solid^probe).volume(),probe.volume(),places=10)
        self.assertEqual(details['swept_triangle_count'],2)
    def test_tied_direction_prefers_more_painted_coverage(self):
        # Two outward-facing planar patches are perfectly coherent on Y/Z;
        # the larger horizontal patch should choose upward, not axis order.
        painted=np.array([[[0,0,0],[0,0,1],[1,0,0]],[[0,0,0],[4,0,0],[0,4,0]]],float)
        self.assertEqual(interface_direction(painted),'+Z')

    def test_coplanar_batch_does_not_bridge_separate_painted_strips(self):
        from cutting_engine.edge_sweep import planar_edge_sweeps
        triangles=[]
        for low in [0,3]:
            a=[0,low,1];b=[0,low+1,1];c=[0,low+1,2];d=[0,low,2]
            triangles.extend([[a,b,c],[a,c,d]])
        slabs=planar_edge_sweeps(np.array(triangles,float),5,.005)
        solid=mf.Manifold.batch_boolean(slabs,mf.OpType.Add)
        for y in [.5,3.5]:
            probe=mf.Manifold.cube([.002,.01,.01]).translate([-.001,y,3])
            self.assertAlmostEqual((solid^probe).volume(),probe.volume(),places=10)
        gap=mf.Manifold.cube([.002,.01,.01]).translate([-.001,2,3])
        self.assertAlmostEqual((solid^gap).volume(),0,places=10)
