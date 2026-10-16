"""Save an approved repair into a copy of its original project archive."""
import io
import json
import zipfile
import xml.etree.ElementTree as ET
import numpy as np
import trimesh
from .model import NS, load_3mf


def export_repaired(model):
    if not model.diagnostics.get('repair_approval', {}).get('approved'):
        raise ValueError('Review and approve the repair before saving it.')
    origin, repair = model.archive_source, model.repair_export
    if origin is None or repair is None:
        raise ValueError('Reload the original 3MF and review its repair to enable repair saving.')
    if any(code is None for code in repair['codes']):
        raise ValueError('A repaired face reverses a subdivided paint boundary. Exact paint export is unavailable for this repair.')
    archive = zipfile.ZipFile(io.BytesIO(origin['data']))
    document = archive.read(origin['path'])
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(document), events=['start-ns']):
        if not prefix.startswith('ns'):
            ET.register_namespace(prefix, uri)
    root = ET.fromstring(document)
    geometry = root.find(f'm:resources/m:object[@id="{origin["object_id"]}"]/m:mesh', NS)
    geometry.clear()
    core = '{' + NS['m'] + '}'
    vertices = ET.SubElement(geometry, core+'vertices')
    local = trimesh.transform_points(model.source.vertices, np.linalg.inv(origin['matrix']))
    for vertex in local:
        ET.SubElement(vertices, core+'vertex', **{k: format(float(v), '.17g') for k,v in zip('xyz',vertex)})
    triangles = ET.SubElement(geometry, core+'triangles')
    for face, code in zip(repair['faces'], repair['codes']):
        attrs = {k:str(int(v)) for k,v in zip(['v1','v2','v3'],face)}
        if code:
            attrs['paint_color'] = code
        ET.SubElement(triangles, core+'triangle', attrs)
    replacement = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as saved:
        for entry in archive.infolist():
            # Cached toolpaths must never survive a geometry repair.
            if entry.filename.lower().endswith(('.gcode','.gcode.md5')) or 'slice_info' in entry.filename.lower():
                continue
            saved.writestr(entry, replacement if entry.filename == origin['path'] else archive.read(entry.filename))
        saved.writestr('Metadata/model-cleavage-repair.json', json.dumps(model.diagnostics['repair_approval']))
    data = output.getvalue()
    checked = load_3mf(data, model.name)
    if not checked.cut_ready or len(checked.source.faces) != len(model.source.faces) or not np.isclose(checked.source.volume, model.source.volume, rtol=1e-9, atol=1e-6):
        raise ValueError('Repaired project failed its reload verification; nothing was saved.')
    for state in np.unique(model.states):
        expected = trimesh.triangles.area(model.triangles[model.states == state]).sum()
        actual = trimesh.triangles.area(checked.triangles[checked.states == state]).sum()
        if not np.isclose(actual, expected, rtol=1e-9, atol=1e-6):
            raise ValueError('Repaired project failed paint preservation verification; nothing was saved.')
    return data
