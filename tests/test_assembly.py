import sys,pathlib,unittest,io,zipfile,json,xml.etree.ElementTree as ET
from types import SimpleNamespace
ROOT=pathlib.Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import numpy as np
import manifold3d as mf
from cutting_engine.engine import mesh,cut_region,CutParameters,manifold
from cutting_engine.model import PaintedModel,identify_regions
from cutting_engine.assembly import Assembly,check_existing_sockets

def fixture():
    base=mf.Manifold.cube([20,16,12]).translate([-10,-8,0])
    right=mf.Manifold.cube([5,6,6]).translate([10,-3,3])
    left=mf.Manifold.cube([5,6,6]).translate([-15,-3,3])
    source=mesh(base+right+left);triangles=source.triangles;c=triangles.mean(1)
    states=np.where(c[:,0]>10.001,2,np.where(c[:,0]<-10.001,3,1))
    ids,regions=identify_regions(triangles,states)
    return PaintedModel('two-features.3mf',source,triangles,states,ids,regions,['#849CBD','#ff8080','#eeeeee'],{},[])

class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.model=fixture();self.assembly=Assembly(self.model)
        self.right=next(r['id'] for r in self.model.regions if r['state']==2)
        self.left=next(r['id'] for r in self.model.regions if r['state']==3)
    def add(self,region,direction,name):
        result=cut_region(self.assembly.model,CutParameters(region,direction,0,2,mode='interface'))
        return self.assembly.accept(result,name)
    def test_source_cleanup_does_not_hide_untouched_region(self):
        speck=mf.Manifold.cube([.01,.01,.01]).translate([-14.,0.,10.])
        triangles=mesh(speck).triangles
        self.model.source=mesh(manifold(self.model.source)+speck)
        self.model.triangles=np.concatenate([self.model.triangles,triangles])
        self.model.states=np.r_[self.model.states,np.full(len(triangles),3)]
        self.model.region_ids=np.r_[self.model.region_ids,np.full(len(triangles),self.left)]
        self.add(self.right,'+X','Right')
        working=self.assembly.model
        self.assertFalse(working.regions[self.left].get('blocked',False))
        self.assertTrue(np.any(working.region_ids[:working.display_triangles]==self.left))

    def test_painted_speck_bridge_transfers_only_existing_material(self):
        from cutting_engine.printability import painted_speck_bridge
        main=mf.Manifold.cube([1,1,1])
        speck=mf.Manifold.cube([.04,.04,.04]).translate([1.2,.5,.5])
        source=mf.Manifold.cube([1.5,1.1,1.])
        part=main+speck
        bridge,records=painted_speck_bridge(part,source,mesh(speck).triangles,np.array([0,0,1.]))
        self.assertIsNotNone(bridge)
        joined=part+(source^bridge)
        self.assertEqual(len(joined.decompose()),1)
        self.assertAlmostEqual((joined-source).volume(),0,places=9)
        self.assertAlmostEqual((speck-joined).volume(),0,places=9)
        self.assertLessEqual(records[0]['bridge_material_mm3'],.1)
        unrelated=mesh(main).triangles
        self.assertIsNone(painted_speck_bridge(part,source,unrelated,np.array([0,0,1.]))[0])

    def test_second_cut_handles_degenerate_context_faces(self):
        self.add(self.right,'+X','Right')
        model=self.assembly.model
        # Boolean-generated sliver faces may be rejected by the normal routine.
        tiny=np.array([[[0.,0.,0.],[1e-10,0.,0.],[0.,1e-10,0.]]])
        model.triangles=np.concatenate([model.triangles,tiny])
        model.region_ids=np.r_[model.region_ids,len(model.regions)-1]
        model.states=np.r_[model.states,1]
        self.add(self.left,'-X','Left')
        self.assertEqual(len(self.assembly.parts),2)
        self.assertGreater(self.assembly.parts[-1].solid.volume(),0)

    def test_legacy_snapshot_completes_in_spawned_worker(self):
        from dataclasses import asdict
        from cutting_engine.jobs import CutJob
        del self.model.socket_history
        del self.model.display_triangles
        job=CutJob(ROOT,self.model,'legacy-test',asdict(CutParameters(self.right,'+X',0,2,mode='interface')))
        job.process.wait(timeout=90)
        status=job.status()
        self.assertEqual(status['state'],'done', (job.folder/'worker.log').read_text())
        result=job.result()
        self.assertGreater(result.extracted.volume(),0)
        self.assertTrue(result.next_model.socket_history)
        self.assertTrue(result.next_model.payload()['body_positions'])

    def test_two_cuts_use_remaining_body_and_keep_first_part_intact(self):
        original=self.model.source.volume;a=self.add(self.right,'+X','Right');volume=a.solid.volume();remaining=self.assembly.model.source.volume
        self.assertTrue(self.assembly.model.regions[self.right]['blocked'])
        self.assertFalse(self.assembly.model.regions[self.left].get('blocked',False))
        b=self.add(self.left,'-X','Left')
        self.assertEqual(a.solid.volume(),volume);self.assertLess(self.assembly.model.source.volume,remaining)
        self.assertAlmostEqual((a.solid^b.solid).volume(),0,places=7)
        self.assertAlmostEqual(self.model.source.volume,original)
        self.assertTrue(self.assembly.payload()['body_positions'])
        self.assertEqual(len(self.assembly.payload()['assembly']['parts']),2)
    def test_selective_export_contains_only_requested_geometry_with_same_transform(self):
        a=self.add(self.right,'+X','Right');b=self.add(self.left,'-X','Left')
        def inspect(selected):
            z=zipfile.ZipFile(io.BytesIO(self.assembly.export(selected)))
            assembly=zipfile.ZipFile(io.BytesIO(z.read('assembly.3mf')))
            root=ET.fromstring(assembly.read('3D/3dmodel.model'));ns={'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
            objects=root.findall('m:resources/m:object',ns);meshes=[o for o in objects if o.find('m:mesh',ns) is not None]
            report=json.loads(z.read('cut-settings-and-validation.json'))
            return root.find('m:build/m:item',ns).get('transform'),meshes,report,z.namelist()
        all_parts=inspect([a.id,b.id,'body']);one=inspect([a.id]);body=inspect(['body'])
        self.assertEqual(len(all_parts[1]),3);self.assertEqual(len(one[1]),1);self.assertEqual(len(body[1]),1)
        self.assertEqual(one[0],all_parts[0]);self.assertEqual(body[0],all_parts[0])
        self.assertEqual(one[2]['selected_part_ids'],[a.id]);self.assertFalse(one[2]['remaining_body_exported'])
        self.assertEqual(sum(n.endswith('.stl') for n in one[3]),sum(c['closed_after_stl_conversion'] for c in one[2]['stl_checks']))
        if not any(n.endswith('.stl') for n in one[3]):self.assertTrue(one[2]['export_warnings'])
        ns={'m':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
        vertices=np.array([[float(v.get(k)) for k in 'xyz'] for v in one[1][0].findall('.//m:vertex',ns)])
        np.testing.assert_allclose(vertices.min(0),mesh(a.solid).bounds[0])
    def test_undo_and_reset_restore_paint_and_original_geometry(self):
        a=self.add(self.right,'+X','Right');volume=self.assembly.model.source.volume
        self.add(self.left,'-X','Left');self.assembly.undo()
        self.assertEqual(len(self.assembly.parts),1);self.assertAlmostEqual(self.assembly.model.source.volume,volume)
        self.assertFalse(self.assembly.model.regions[self.left].get('blocked',False))
        self.assembly.reset();self.assertIs(self.assembly.model,self.model);self.assertEqual(self.assembly.parts,[])
    def test_socket_wall_loss_is_rejected(self):
        self.add(self.right,'+X','Right')
        point=self.assembly.model.socket_history[0]['triangles'][0].mean(0)
        base=manifold(self.assembly.model.source);damaged=base-mf.Manifold.cube([1,1,1],True).translate(point.tolist())
        with self.assertRaisesRegex(ValueError,'existing socket'):
            check_existing_sockets(self.assembly.model,SimpleNamespace(remainder=damaged))
    def test_names_selection_and_overlap_are_checked_without_mutation(self):
        a=self.add(self.right,'+X','Right')
        self.assembly.rename(a.id,'../Ear');self.assertEqual(a.name,'../Ear')
        bundle=zipfile.ZipFile(io.BytesIO(self.assembly.export([a.id])))
        self.assertFalse(any(n.startswith('.') or '/' in n for n in bundle.namelist()))
        for selection in [[],['unknown'],[a.id,a.id]]:
            with self.assertRaises(ValueError):self.assembly.export(selection)
        with self.assertRaises(ValueError):self.assembly.rename(a.id,' ')
        with self.assertRaises(ValueError):self.assembly.accept(SimpleNamespace(parameters=CutParameters(self.left,'-X',0),extracted=a.solid,remainder=manifold(self.assembly.model.source)),'Overlap')
        self.assertEqual(len(self.assembly.parts),1)

if __name__=='__main__':unittest.main()
