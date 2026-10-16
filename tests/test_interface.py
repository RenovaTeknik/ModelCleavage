import pathlib,sys,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
import manifold3d as mf
from cutting_engine.engine import cut_region,CutParameters,mesh
from cutting_engine.model import PaintedModel
class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source=mesh(mf.Manifold.sphere(5,24))
        triangles=source.triangles;c=triangles.mean(axis=1)
        selected=c[:,2]>1+.5*np.sin(2*np.arctan2(c[:,1],c[:,0]))
        cls.model=PaintedModel('curved',source,triangles,np.where(selected,2,1),np.where(selected,1,0),[{'state':1},{'state':2}],['#849cbd','#ff9999'],{},[])
    def test_curved_feature_is_solid_and_hidden_cap_is_flat(self):
        result=cut_region(self.model,CutParameters(1,'+Z',999,1,mode='interface'))
        report=result.report['interface'];surface=mesh(result.extracted)
        self.assertTrue(surface.is_watertight)
        self.assertTrue(report['paint_boundary_constrained'])
        self.assertTrue(report['constant_cross_section'])
        self.assertLessEqual(report['interface_outline_deviation_mm'],.15)
        self.assertTrue(report['outward_expanding_profile'])
        self.assertAlmostEqual(report['missing_paint_profile_area_mm2'],0)
        self.assertTrue(result.report['insertion_path']['checked'])
        self.assertLess(result.report['insertion_path']['max_overlap_mm3'],.001)
        self.assertAlmostEqual(report['deepest_interface']-report['cap_plane'],1)
        self.assertAlmostEqual(surface.bounds[0,2],report['cap_plane'],places=5)
        probe=mf.Manifold.sphere(.4,16).translate([0,0,4])
        self.assertAlmostEqual((result.extracted ^ probe).volume(),probe.volume(),places=5)
        self.assertLess(result.report['overlap_mm3'],.001)
    def test_returning_curl_behind_root_cap_is_preserved(self):
        outline=np.array([[0,4],[4,4],[4,10],[-2,10],[-2,8],[2,8],[2,6],[0,6]],dtype=float)
        feature=mf.CrossSection([outline]).extrude(2)
        base=mf.Manifold.cube([5,10,2]).translate([-5,-5,0])
        surface=mesh(base+feature);centres=surface.triangles_center
        painted=(centres[:,0]>1e-7)|(centres[:,1]>5+1e-7)
        model=PaintedModel('returning curl',surface,surface.triangles,np.where(painted,2,1),np.where(painted,1,0),[{'state':1},{'state':2}],['#849cbd','#ff9999'],{},[])
        result=cut_region(model,CutParameters(1,'+X',0,1,mode='interface'))
        tip=mf.Manifold.cube([.2,.2,.2]).translate([-1.8,8.8,.8])
        self.assertAlmostEqual((result.extracted ^ tip).volume(),tip.volume(),places=7)
        self.assertLess(mesh(result.extracted).bounds[0,0],-1.99)
        self.assertAlmostEqual(result.report['interface']['cap_plane'],-1,places=6)
        self.assertTrue(result.report['interface']['full_painted_surface_sweep'])
        self.assertEqual(result.report['painted_surface_coverage']['missing_samples'],0)
        self.assertTrue(result.report['insertion_path']['checked'])

    def test_fit_adds_cap_depth_without_changing_part(self):
        nominal=cut_region(self.model,CutParameters(1,'+Z',0,1,mode='interface'))
        fit=cut_region(self.model,CutParameters(1,'+Z',0,1,depth_clearance=.2,mode='interface'))
        self.assertAlmostEqual(nominal.extracted.volume(),fit.extracted.volume(),places=5)
        self.assertGreater(fit.report['fit_gap_volume_mm3'],0)
    def test_side_clearance_enlarges_straight_pocket(self):
        nominal=cut_region(self.model,CutParameters(1,'+Z',0,1,mode='interface'))
        fit=cut_region(self.model,CutParameters(1,'+Z',0,1,side_clearance=.15,mode='interface'))
        self.assertAlmostEqual(nominal.extracted.volume(),fit.extracted.volume(),places=6)
        self.assertGreater(fit.report['fit_gap_volume_mm3'],0)
        self.assertLess(fit.report['insertion_path']['max_overlap_mm3'],.001)

    def test_export_omits_stl_that_loses_thickness_in_float32(self):
        import io,json,zipfile
        from cutting_engine.engine import CutResult
        from cutting_engine.exporter import export_bundle
        thin=mf.Manifold.cube([1,1,.000001]).translate([130.12345678901234,130.98765432109876,130])
        base=mf.Manifold.cube([2,2,2])
        result=CutResult(CutParameters(1,'+Z',0,1),thin,base,base,{})
        with zipfile.ZipFile(io.BytesIO(export_bundle(self.model,result))) as archive:
            self.assertIn('assembly.3mf',archive.namelist())
            self.assertNotIn('excised-1.stl',archive.namelist())
            report=json.loads(archive.read('cut-settings-and-validation.json'))
            self.assertTrue(report['export_warnings'])
            # Indexed 3MF must retain full double precision even when STL is
            # unsafe; rounding here can collapse distinct close vertices.
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(io.BytesIO(archive.read('assembly.3mf'))) as project:
                xml=ET.fromstring(project.read('3D/3dmodel.model'))
            first=xml.find('.//{*}mesh/{*}vertices')
            encoded={tuple(float(v.attrib[a]) for a in 'xyz') for v in first}
            original={tuple(v) for v in mesh(thin).vertices}
            self.assertEqual(encoded,original)

    def test_insertion_path_rejects_a_trapping_lip(self):
        from cutting_engine.engine import check_insertion_path
        part=mf.Manifold.cube([1,1,1])
        lip=mf.Manifold.cube([2,2,.5]).translate([-.5,-.5,2])
        from cutting_engine.engine import InsertionCollision
        with self.assertRaises(InsertionCollision) as caught:
            check_insertion_path(part,lip,[0,0,1],4)
        collision=caught.exception
        self.assertAlmostEqual(collision.collision_report['max_overlap_mm3'],.5,places=9)
        self.assertAlmostEqual(collision.collision_report['at_offset_mm'],2.,places=9)
        self.assertEqual(collision.collision_report['tolerance_mm3'],.001)
        np.testing.assert_allclose(collision.collision_report['bounds'],[[0,0,2],[1,1,2.5]])
        self.assertTrue(collision.diagnostic_payload()['overlap'])
        self.assertEqual(collision.collision_report['component_count'],1)
