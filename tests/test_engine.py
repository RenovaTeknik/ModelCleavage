import io
import pathlib
import sys
import unittest
import zipfile
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.runtime' / 'python'))
sys.path.insert(0, str(ROOT / 'src'))
import numpy as np
import trimesh
import manifold3d as mf
from cutting_engine.model import decode_paint, load_3mf, identify_regions, PaintedModel
from cutting_engine.engine import CutParameters, cut_region, manifold, mesh, assert_faces_bound_material, prismatic_zones
from cutting_engine.exporter import export_bundle
from cutting_engine.repair import propose_repair


def fixture(translation='1 0 0 0 1 0 0 0 1 0 0 0'):
    base = mf.Manifold.cube([10, 10, 10]).translate([-5, -5, -5])
    protrusion = mf.Manifold.cube([4, 5, 4]).translate([-2, -10, -2])
    result = (base + protrusion).to_mesh64()
    vertices, faces = np.asarray(result.vert_properties)[:, :3], np.asarray(result.tri_verts)
    root = ET.Element('model', xmlns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02', unit='millimeter')
    resources = ET.SubElement(root, 'resources')
    obj = ET.SubElement(resources, 'object', id='1', type='model')
    mesh = ET.SubElement(obj, 'mesh')
    ve, te = ET.SubElement(mesh, 'vertices'), ET.SubElement(mesh, 'triangles')
    for v in vertices:
        ET.SubElement(ve, 'vertex', **{k: str(x) for k, x in zip('xyz', v)})
    for face in faces:
        attrs = {k: str(x) for k, x in zip(['v1', 'v2', 'v3'], face)}
        if vertices[face].mean(0)[1] < -5.001:
            attrs['paint_color'] = '8'
        ET.SubElement(te, 'triangle', **attrs)
    ET.SubElement(ET.SubElement(root, 'build'), 'item', objectid='1', transform=translation)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as z:
        z.writestr('_rels/.rels', '<Relationships><Relationship Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" Target="/3D/3dmodel.model"/></Relationships>')
        z.writestr('3D/3dmodel.model', ET.tostring(root))
        z.writestr('Metadata/project_settings.config', '{"filament_colour":["#849CBD","#FF8080"]}')
    return output.getvalue()


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = load_3mf(fixture(), 'fixture.3mf')
        cls.pink = next(r['id'] for r in cls.model.regions if r['state'] == 2)

    def test_paint_tree_order_and_area(self):
        triangle = np.array([[0., 0, 0], [4., 0, 0], [0., 4, 0]])
        leaves = decode_paint(triangle, '481')
        self.assertEqual([state for _, state in leaves], [2, 1])
        self.assertAlmostEqual(sum(trimesh.triangles.area(np.array([t]))[0] for t, _ in leaves), 8)
        self.assertEqual(decode_paint(triangle, '1C')[0][1], 4)
        with self.assertRaises(ValueError):
            decode_paint(triangle, 'C')

    def test_separated_matching_colours_stay_separate(self):
        a = np.array([[0., 0, 0], [1., 0, 0], [0., 1, 0]])
        triangles = np.array([a, a + [4, 0, 0]])
        ids, regions = identify_regions(triangles, np.array([2, 2]))
        self.assertEqual(len(regions), 2)
        self.assertNotEqual(ids[0], ids[1])

    def test_tiny_islands_group_only_with_nearby_large_matching_region(self):
        large = np.array([[0.,0,0],[4.,0,0],[0.,4,0]])
        near = np.array([[4.1,0,0],[4.2,0,0],[4.1,.1,0]])
        remote = near + [3,0,0]
        other = near + [0,0,.01]
        triangles = np.array([large,near,remote,other])
        states = np.array([1,1,1,2])
        before = triangles.copy()
        ids, regions = identify_regions(triangles,states)
        self.assertEqual(ids[0],ids[1])
        self.assertNotEqual(ids[0],ids[2])
        self.assertNotEqual(ids[0],ids[3])
        self.assertEqual(regions[ids[0]]['grouped_islands'],1)
        np.testing.assert_array_equal(before,triangles)
        self.assertEqual(states.tolist(),[1,1,1,2])

    def test_source_build_transform_is_applied_once(self):
        model = load_3mf(fixture('1 0 0 0 1 0 0 0 1 20 20 5'))
        np.testing.assert_allclose(model.source.bounds, [[15, 10, 0], [25, 25, 10]])

    def test_protrusion_is_solid_and_root_is_two_mm(self):
        result = cut_region(self.model, CutParameters(self.pink, '-Y', 5, 2))
        inner = mf.Manifold.cube([3, 4, 3]).translate([-1.5, -9.5, -1.5])
        self.assertLess(abs((inner - result.extracted).volume()), 1e-8)
        points = np.array(result.extracted.to_mesh64().vert_properties)[:, :3]
        self.assertAlmostEqual(points[:, 1].max(), -3., places=5)
        self.assertTrue(result.report['closed'])
        self.assertAlmostEqual(result.extracted.volume() + result.nominal_remainder.volume(), self.model.source.volume, places=5)

    def test_clearance_changes_pocket_not_part(self):
        nominal = cut_region(self.model, CutParameters(self.pink, '-Y', 5))
        fit = cut_region(self.model, CutParameters(self.pink, '-Y', 5, side_clearance=.2, depth_clearance=.1))
        self.assertAlmostEqual(nominal.extracted.volume(), fit.extracted.volume(), places=8)
        self.assertLess(fit.remainder.volume(), nominal.remainder.volume())
        self.assertGreater(fit.report['fit_gap_volume_mm3'], 0)
        self.assertLess(fit.report['overlap_mm3'], .001)

    def test_export_is_one_positioned_assembly(self):
        result = cut_region(self.model, CutParameters(self.pink, '-Y', 5))
        data = export_bundle(self.model, result)
        with zipfile.ZipFile(io.BytesIO(data)) as bundle:
            assembly = bundle.read('assembly.3mf')
            self.assertIn('excised-1.stl', bundle.namelist())
        with zipfile.ZipFile(io.BytesIO(assembly)) as z:
            root = ET.fromstring(z.read('3D/3dmodel.model'))
            ns = {'m': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
            self.assertEqual(len(root.findall('m:build/m:item', ns)), 1)
        loaded = trimesh.load_scene(io.BytesIO(assembly), file_type='3mf', process=False)
        self.assertEqual(len(loaded.geometry), 2)
        self.assertTrue(all(m.is_watertight for m in loaded.geometry.values()))
        self.assertAlmostEqual(loaded.bounds[0, 2], 0)
        self.assertAlmostEqual(loaded.bounds[:, 0].mean(), 128)

    def test_invalid_settings_are_rejected(self):
        with self.assertRaises(ValueError):
            cut_region(self.model, CutParameters(self.pink, '-Y', 5, side_clearance=-.1))
        with self.assertRaises(ValueError):
            cut_region(self.model, CutParameters(self.pink, '-Y', 5, fastener='ball'))
        with self.assertRaises(ValueError):
            cut_region(self.model, CutParameters(self.pink, '-Y', 5, depth=0))

    def test_invalid_mesh_loads_for_inspection_and_repair_is_separate(self):
        boxes = trimesh.util.concatenate([trimesh.creation.box([10, 10, 10]),
                                          trimesh.creation.box([10, 10, 10], transform=trimesh.transformations.translation_matrix([10, 10, 0]))])
        boxes.merge_vertices()
        with zipfile.ZipFile(io.BytesIO(fixture())) as z:
            files = {name: z.read(name) for name in z.namelist()}
        root = ET.fromstring(files['3D/3dmodel.model'])
        ns = {'m': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
        node = root.find('.//m:mesh', ns)
        for child in list(node): node.remove(child)
        ve = ET.SubElement(node, '{'+ns['m']+'}vertices')
        te = ET.SubElement(node, '{'+ns['m']+'}triangles')
        for v in boxes.vertices: ET.SubElement(ve, '{'+ns['m']+'}vertex', **{k: str(x) for k, x in zip('xyz', v)})
        for f in boxes.faces: ET.SubElement(te, '{'+ns['m']+'}triangle', **{k: str(x) for k, x in zip(['v1','v2','v3'], f)})
        files['3D/3dmodel.model'] = ET.tostring(root)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as z:
            for name, content in files.items(): z.writestr(name, content)
        model = load_3mf(data.getvalue())
        self.assertFalse(model.cut_ready)
        self.assertGreater(model.diagnostics['nonmanifold_edges'], 0)
        self.assertTrue(model.payload()['problem_positions'])
        original_faces = model.source.faces.copy()
        with self.assertRaisesRegex(ValueError, 'Inspection-only'):
            cut_region(model, CutParameters(0, '+Z', 5))
        proposed = propose_repair(model)
        self.assertFalse(model.cut_ready)
        np.testing.assert_array_equal(original_faces, model.source.faces)
        self.assertTrue(proposed.candidate.cut_ready)
        self.assertTrue(proposed.report['paint_preserved_on_retained_faces'])
        from cutting_engine.repair_export import export_repaired
        with self.assertRaisesRegex(ValueError, 'approve'):
            export_repaired(proposed.candidate)
        proposed.candidate.diagnostics['repair_approval'] = {'approved': True, 'report': proposed.report}
        saved = export_repaired(proposed.candidate)
        reloaded = load_3mf(saved)
        self.assertTrue(reloaded.cut_ready)
        np.testing.assert_allclose(reloaded.source.bounds, proposed.candidate.source.bounds, atol=1e-9)
        self.assertAlmostEqual(reloaded.source.volume, proposed.candidate.source.volume, places=7)
        self.assertEqual(reloaded.settings, model.settings)
        self.assertFalse(model.cut_ready)


    def test_positive_volume_sheet_below_geometry_resolution_is_rejected(self):
        # Closed topology and positive volume are insufficient for a real part.
        sheet = mf.Manifold.cube([20, 20, 1e-6])
        self.assertGreater(sheet.volume(), 0)
        self.assertTrue(mesh(sheet).is_watertight)
        with self.assertRaisesRegex(ValueError, 'zero-thickness|thinner'):
            assert_faces_bound_material(sheet)

    def test_top_edge_cut_has_only_material_backed_vertical_walls(self):
        from shapely.geometry import Polygon, Point
        base = mf.Manifold.cube([60, 60, 20]).translate([-30, -30, -10])
        top = mf.CrossSection([np.array([[-20, -15], [20, -15], [0, 20]])]).extrude(25).translate([0, 0, 10])
        source = mesh(base + top)
        # Painted footprint meets the original triangular feature's exterior.
        painted = np.array([[[-20., -15, 35], [20., -15, 35], [0., 5, 35]]])
        model = PaintedModel('top-edge.3mf', source, painted, np.array([2]), np.array([0]),
                             [{'id': 0, 'state': 2}], ['#849CBD', '#FFFFFF'], {}, [])
        result = cut_region(model, CutParameters(0, '+Z', 10, 2))
        self.assertGreater(result.report['regularized_sections'], 0)
        for solid in [result.extracted, result.remainder]:
            section = solid.slice(20).to_polygons()
            boundary = Polygon(section[0]).boundary
            surface = mesh(solid)
            selected = (surface.triangles_center[:, 2] > 10.01) & (abs(surface.face_normals[:, 2]) < .01)
            for centre in surface.triangles_center[selected]:
                self.assertLess(Point(centre[:2]).distance(boundary), 1e-5)

    def test_sloped_features_are_not_assumed_prismatic(self):
        cone = mesh(mf.Manifold.cylinder(10, 5, 0, 32))
        self.assertEqual(prismatic_zones(cone, [0, 0, 1], 0), [])

    def test_base_paint_touching_feature_does_not_make_full_height_sheet(self):
        base = mf.Manifold.cube([60, 60, 20]).translate([-30, -30, -10])
        top = mf.CrossSection([np.array([[-20, -15], [20, -15], [0, 20]])]).extrude(25).translate([0, 0, 10])
        source = mesh(base + top)
        painted = np.array([[[-20., -15, 35], [20., -15, 35], [0., 5, 35]],
                            [[0., 20, 10], [0., 22, 10], [2., 21, 10]]])
        model = PaintedModel('base-touch.3mf', source, painted, np.array([2, 2]), np.array([0, 0]),
                             [{'id': 0, 'state': 2}], ['#849CBD', '#FFFFFF'], {}, [])
        result = cut_region(model, CutParameters(0, '+Z', 10, 2))
        # A base patch touches the feature tip. Its numerical outline overlap
        # must not extrude into a full-height blade on the feature above it.
        probe = mf.Manifold.cube([.001, .001, 1]).translate([-.0005, 19.998, 20])
        self.assertLess(abs((result.extracted ^ probe).volume()), 1e-10)
        self.assertAlmostEqual((result.remainder ^ probe).volume(), probe.volume(), places=10)

    def test_basicshapes_white_top_has_no_off_section_planes(self):
        from shapely import distance, points, union_all
        from shapely.geometry import LineString
        model = load_3mf((ROOT / 'examples' / 'BasicShapes001.3mf').read_bytes())
        region = next(r for r in model.regions if r['state'] == 4 and r['bounds'][1][2] > 120)
        result = cut_region(model, CutParameters(region['id'], '+Z', 100, 2))
        for solid in [result.extracted, result.remainder]:
            loops = solid.slice(110).to_polygons()
            boundary = union_all([LineString(np.vstack([p, p[0]])) for p in loops])
            surface = mesh(solid)
            selected = (surface.triangles_center[:, 2] > 100.01) & (abs(surface.face_normals[:, 2]) < .01)
            offsets = distance(points(surface.triangles_center[selected, :2]), boundary)
            self.assertEqual(int((offsets > 1e-5).sum()), 0)


if __name__ == '__main__':
    unittest.main()
