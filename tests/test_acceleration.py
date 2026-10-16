import pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
import trimesh
from cutting_engine.acceleration import SurfaceDistance,raster_roof
from cutting_engine.jobs import CutJob
from test_engine import fixture
from cutting_engine.model import load_3mf
from cutting_engine.engine import CutParameters
from dataclasses import asdict

class AccelerationTests(unittest.TestCase):
    def test_reusable_distance_matches_exact_reference_near_and_far(self):
        surface=trimesh.creation.icosphere(subdivisions=1)
        points=np.random.default_rng(64).normal(size=(90,3))*4
        points=np.vstack([points,surface.vertices[:5]])
        query=SurfaceDistance(surface.triangles)
        expected=trimesh.proximity.closest_point_naive(surface,points)[1]
        np.testing.assert_allclose(query(points),expected,atol=1e-12,rtol=1e-12)
        np.testing.assert_allclose(query(points[:7]),expected[:7],atol=1e-12,rtol=1e-12)

    def test_local_raster_matches_full_grid_scan(self):
        triangles=np.random.default_rng(8).uniform(-1,1,(100,3,3))
        low=np.array([-1.1,-1.1]);shape=(24,24);step=.1
        xx,yy=np.meshgrid(low[0]+np.arange(shape[0])*step,low[1]+np.arange(shape[1])*step,indexing='ij')
        xy=np.column_stack([xx.ravel(),yy.ravel()]);expected=np.full(len(xy),-np.inf)
        for triangle in triangles:
            a,b,c=triangle
            d=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            if d<1e-10:continue
            ids=np.flatnonzero(((xy>=triangle[:,:2].min(0)-1e-7)&(xy<=triangle[:,:2].max(0)+1e-7)).all(1))
            dx=xy[ids,0]-a[0];dy=xy[ids,1]-a[1]
            q=(dx*(c[1]-a[1])-dy*(c[0]-a[0]))/d;r=((b[0]-a[0])*dy-(b[1]-a[1])*dx)/d
            inside=(q>=-1e-7)&(r>=-1e-7)&(q+r<=1+1e-7)
            expected[ids[inside]]=np.maximum(expected[ids[inside]],a[2]+q[inside]*(b[2]-a[2])+r[inside]*(c[2]-a[2]))
        actual,tests=raster_roof(triangles,low,shape,step)
        np.testing.assert_array_equal(actual,expected)
        self.assertLess(tests,len(triangles)*len(xy))

    def test_completed_worker_reconstructs_full_precision_solids(self):
        import time
        model=load_3mf(fixture())
        region=next(r['id'] for r in model.regions if r['state']==2)
        job=CutJob(ROOT,model,'test',asdict(CutParameters(region,'-Y',5,2)))
        try:
            started=time.monotonic()
            while job.status()['state']=='running' and time.monotonic()-started<15:
                time.sleep(.05)
            self.assertEqual(job.status()['state'],'done',job.status())
            result=job.result()
            self.assertAlmostEqual(result.extracted.volume()+result.nominal_remainder.volume(),model.source.volume,places=6)
            self.assertIn('total_seconds',result.report['performance'])
            self.assertTrue(result.report['closed'])
        finally:job.cancel()

    def test_cancel_terminates_worker_and_preserves_loaded_model(self):
        model=load_3mf(fixture())
        before=model.source.faces.copy()
        job=CutJob(ROOT,model,'test',asdict(CutParameters(1,'-Y',5,2)))
        self.assertIsNone(job.process.poll())
        job.cancel()
        self.assertIsNotNone(job.process.poll())
        self.assertEqual(job.status()['state'],'cancelled')
        self.assertFalse((job.folder/'result.pkl').exists())
        self.assertFalse((job.folder/'input.pkl').exists())
        np.testing.assert_array_equal(model.source.faces,before)

if __name__=='__main__':unittest.main()
