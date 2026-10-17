from dataclasses import asdict
import re
import io
import json
import zipfile
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
from .engine import mesh
from . import __version__, __release_name__

NS = 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'


def export_bundle(model, result, *, named_solids=None, report_override=None):
    pieces = []
    selected_state = model.regions[result.parameters.region]['state']
    base_state = int(np.bincount(model.states).argmax())
    for name, solid, state in (named_solids if named_solids is not None else [('excised', result.extracted, selected_state), ('base', result.remainder, base_state)]):
        for index, part in enumerate(solid.decompose(), 1):
            pieces.append((f'{name}-{index}', mesh(part), state))
    ET.register_namespace('', NS)
    root = ET.Element('{' + NS + '}model', unit='millimeter', attrib={'xml:lang': 'en-US'})
    ET.SubElement(root, 'metadata', name='Application').text = f'Model Cleavage {__version__} - {__release_name__}'
    ET.SubElement(root, 'metadata', name='BambuStudio:3mfVersion').text = '1'
    resources = ET.SubElement(root, 'resources')
    config = ET.Element('config')
    assembly_id = len(pieces) + 1
    objconfig = ET.SubElement(config, 'object', id=str(assembly_id), auto_drop='0')
    ET.SubElement(objconfig, 'metadata', key='name', value='Model Cleavage excision')
    ET.SubElement(objconfig, 'metadata', key='extruder', value=str(base_state))
    for index, (name, surface, state) in enumerate(pieces, 1):
        obj = ET.SubElement(resources, 'object', id=str(index), name=name, type='model')
        me = ET.SubElement(obj, 'mesh')
        vertices, triangles = ET.SubElement(me, 'vertices'), ET.SubElement(me, 'triangles')
        for vertex in surface.vertices:
            ET.SubElement(vertices, 'vertex', **{k: format(float(v), '.17g') for k, v in zip('xyz', vertex)})
        for face in surface.faces:
            ET.SubElement(triangles, 'triangle', **{k: str(int(v)) for k, v in zip(['v1', 'v2', 'v3'], face)})
        part = ET.SubElement(objconfig, 'part', id=str(index), subtype='normal_part')
        ET.SubElement(part, 'metadata', key='name', value=name)
        ET.SubElement(part, 'metadata', key='extruder', value=str(state))
        ET.SubElement(part, 'metadata', key='matrix', value='1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1')
    obj = ET.SubElement(resources, 'object', id=str(assembly_id), type='model', name='Model Cleavage excision')
    components = ET.SubElement(obj, 'components')
    for index in range(1, len(pieces) + 1):
        ET.SubElement(components, 'component', objectid=str(index), transform='1 0 0 0 1 0 0 0 1 0 0 0')
    bounds = model.source.bounds
    shift = [128 - bounds[:, 0].mean(), 128 - bounds[:, 1].mean(), -bounds[0, 2]]
    build = ET.SubElement(root, 'build')
    ET.SubElement(build, 'item', objectid=str(assembly_id), printable='1', auto_drop='0', transform='1 0 0 0 1 0 0 0 1 ' + ' '.join(format(float(v), '.17g') for v in shift))
    plate = ET.SubElement(config, 'plate')
    ET.SubElement(plate, 'metadata', key='plater_id', value='1')
    instance = ET.SubElement(plate, 'model_instance')
    ET.SubElement(instance, 'metadata', key='object_id', value=str(assembly_id))
    ET.SubElement(instance, 'metadata', key='instance_id', value='0')
    ET.SubElement(instance, 'metadata', key='identify_id', value='1')
    content = b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>'
    rels = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>'
    project = io.BytesIO()
    with zipfile.ZipFile(project, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content)
        z.writestr('_rels/.rels', rels)
        z.writestr('3D/3dmodel.model', ET.tostring(root, encoding='utf-8', xml_declaration=True))
        z.writestr('Metadata/model_settings.config', ET.tostring(config, encoding='utf-8', xml_declaration=True))
        z.writestr('Metadata/project_settings.config', json.dumps(model.settings))
    report = {'application_version': __version__, 'release_name': __release_name__, 'model': model.name, 'parameters': asdict(result.parameters), 'validation': result.report,
              'approved_repair': model.diagnostics.get('repair_approval'),
              'export_placement_shift_mm': shift,
              'note': 'The extracted region and base have solid colour assignments. Remaining original paint is not carried onto the base in this prototype export.'}
    if report_override:report.update(report_override)
    stl_files = {}
    stl_checks = []
    export_warnings = []
    for name, surface, _ in pieces:
        data = surface.export(file_type='stl')
        imported = trimesh.load(io.BytesIO(data), file_type='stl', process=True)
        valid = bool(imported.is_watertight and imported.is_winding_consistent and imported.volume > 0)
        stl_checks.append({'name': name, 'closed_after_stl_conversion': valid})
        if valid:
            filename=re.sub(r'[^A-Za-z0-9_.-]+','-',name).strip('.-') or 'part'
            if named_solids is not None:filename=f'{len(stl_files)+1:03d}-{filename}'
            if filename+'.stl' in stl_files:filename=f'{len(stl_files)+1}-{filename}'
            stl_files[filename + '.stl'] = data
        else:
            export_warnings.append(f'{name}: STL omitted because its coordinate precision collapses small edges. Use the full-precision assembly.3mf.')
    report['stl_checks'] = stl_checks
    report['export_warnings'] = export_warnings
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('assembly.3mf', project.getvalue())
        for name, data in stl_files.items():
            z.writestr(name, data)
        if export_warnings:
            z.writestr('STL export notes.txt', '\n'.join(export_warnings))
        z.writestr('cut-settings-and-validation.json', json.dumps(report, indent=2))
        z.writestr('READ ME.txt', 'Assembly retains relative part positions. STL files use the same model coordinates. Only the selected accepted parts and/or remaining body are included. See the JSON report for each cut and its fit allocation. Plain inserts and optional glue keys are supported. Review before printing. Remaining original paint is not retained on the base export.\n')
    return bundle.getvalue()
