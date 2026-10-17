from __future__ import annotations

import base64
import io
import json
import posixpath
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import numpy as np
import trimesh
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

NS = {'m': 'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
PRODUCTION = '{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}'
DIRECTIONS = {'+X': [1, 0, 0], '-X': [-1, 0, 0], '+Y': [0, 1, 0], '-Y': [0, -1, 0], '+Z': [0, 0, 1], '-Z': [0, 0, -1]}


def triangle_normals(triangles):
    """Keep one normal per input face, including zero normals for invalid faces.

    Trimesh compacts normals for degenerate triangles; callers using face masks
    need the original indexing preserved.
    """
    normals, valid = trimesh.triangles.normals(triangles)
    aligned = np.zeros((len(triangles), 3), dtype=float)
    aligned[valid] = normals
    return aligned


def interface_direction(triangles):
    normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
    coverage=np.abs(normals).sum(axis=0)
    coherence=np.divide(np.abs(normals.sum(axis=0)),coverage,out=np.zeros(3),where=coverage>1e-12)
    tied=coherence>=coherence.max()-1e-6
    axis=int(np.argmax(np.where(tied,coverage,-1.)))
    return ('+' if normals[:,axis].sum()>=0 else '-')+'XYZ'[axis]


def packed(array, dtype='<f4'):
    return base64.b64encode(np.asarray(array, dtype=dtype).tobytes()).decode('ascii')


def transform(value):
    if not value:
        return np.eye(4)
    values = np.array([float(v) for v in value.split()])
    if len(values) != 12:
        raise ValueError('Invalid 3MF transform.')
    matrix = np.eye(4)
    matrix[:3, :] = values.reshape(4, 3).T
    return matrix


def decode_paint(triangle, code):
    """Decode a complete Orca/Prusa TriangleSelector tree, preserving child order."""
    if not code:
        return [(triangle, 0)]
    cursor = len(code) - 1
    leaves = []

    def nibble():
        nonlocal cursor
        if cursor < 0:
            raise ValueError('Truncated paint subdivision tree.')
        value = int(code[cursor], 16)
        cursor -= 1
        return value

    def visit(t, depth=0):
        if depth > 64:
            raise ValueError('Paint tree exceeds the supported depth.')
        value = nibble()
        count, side = value & 3, value >> 2
        if count == 0:
            state = side
            if state == 3:
                extended = nibble()
                state = 18 + nibble() if extended == 15 else 3 + extended
            leaves.append((t, state))
            return
        if count != 3 and side > 2:
            raise ValueError('Invalid paint subdivision side.')
        side = 0 if count == 3 else side
        p, q, r = t[[side, (side + 1) % 3, (side + 2) % 3]]
        if count == 1:
            mid = (q + r) / 2
            children = [[p, q, mid], [mid, r, p]]
        elif count == 2:
            a, b = (p + q) / 2, (r + p) / 2
            children = [[p, a, b], [a, q, b], [q, r, b]]
        else:
            a, b, c = (p + q) / 2, (q + r) / 2, (r + p) / 2
            children = [[p, a, c], [a, q, b], [b, r, c], [a, b, c]]
        for child in reversed(children):
            visit(np.array(child), depth + 1)

    visit(triangle)
    if cursor != -1:
        raise ValueError('Paint tree has unconsumed data.')
    return leaves


@dataclass
class PaintedModel:
    name: str
    source: trimesh.Trimesh
    triangles: np.ndarray
    states: np.ndarray
    region_ids: np.ndarray
    regions: list
    palette: list
    settings: dict
    warnings: list
    diagnostics: dict = field(default_factory=dict)
    paint_parents: np.ndarray | None = None

    archive_source: dict | None = None
    repair_export: dict | None = None

    socket_history: list = field(default_factory=list)
    display_triangles: int | None = None

    def __setstate__(self, state):
        """Upgrade snapshots made before multi-part session fields existed."""
        self.__dict__.update(state)
        self.__dict__.setdefault("socket_history", [])
        self.__dict__.setdefault("display_triangles", None)

    @property
    def cut_ready(self):
        return bool(self.source.is_watertight and self.source.is_winding_consistent and self.source.volume > 0)

    def base_plane(self, direction):
        n = np.array(DIRECTIONS[direction], dtype=float)
        aligned = self.source.face_normals @ n > .995
        if not aligned.any():
            raise ValueError('No suitable base face in that direction. Set the base plane manually.')
        levels = np.round(self.source.triangles_center[aligned] @ n, 4)
        unique, inverse = np.unique(levels, return_inverse=True)
        areas = np.bincount(inverse, weights=self.source.area_faces[aligned])
        return float(unique[np.argmax(areas)])

    def suggestion(self, region):
        ids = self.region_ids == region
        points = self.triangles[ids]
        areas = trimesh.triangles.area(points)
        normal = triangle_normals(points)
        candidates = []
        for direction, vector in DIRECTIONS.items():
            n = np.array(vector)
            try:
                plane = self.base_plane(direction)
            except ValueError:
                continue
            excursion = max(0., float((points @ n).max() - plane))
            facing = float(np.maximum(normal @ n, 0) @ areas)
            candidates.append((excursion, facing, direction, plane))
        if not candidates:
            return {'direction': '+Z', 'plane': None}
        protruding = [v for v in candidates if v[0] > .1]
        chosen = max(protruding, key=lambda v: (v[0], v[1])) if protruding else max(candidates, key=lambda v: v[1])
        return {'direction': chosen[2], 'plane': chosen[3]}

    def payload(self):
        count=self.display_triangles if self.display_triangles is not None else len(self.triangles)
        return {'body_positions':packed(self.source.triangles) if self.display_triangles is not None else '', 'name': self.name, 'palette': self.palette, 'positions': packed(self.triangles[:count]),
                'states': packed(self.states[:count], '<u4'), 'region_ids': packed(self.region_ids[:count], '<u4'),
                'regions': self.regions, 'bounds': self.source.bounds.tolist(),
                'original_triangles': len(self.source.faces), 'paint_triangles': count,
                'volume': float(self.source.volume), 'warnings': self.warnings,
                'cut_ready': self.cut_ready, 'diagnostics': self.diagnostics,
                'problem_positions': packed(self.source.triangles[problem_faces(self.source)]) if not self.cut_ready else ''}


def problem_faces(source):
    counts = np.bincount(source.edges_unique_inverse)
    invalid_edges = counts != 2
    edges = source.edges
    signs = np.where(edges[:, 0] < edges[:, 1], 1, -1)
    orientation = np.bincount(source.edges_unique_inverse, weights=signs)
    invalid_edges |= (counts == 2) & (orientation != 0)
    bad = invalid_edges[source.edges_unique_inverse].reshape(-1, 3).any(1)
    bad |= source.area_faces < 1e-12
    if source.volume <= 0:
        bad[:] = True
    return bad


def mesh_diagnostics(source):
    counts = np.bincount(source.edges_unique_inverse)
    return {'open_edges': int((counts == 1).sum()), 'nonmanifold_edges': int((counts > 2).sum()),
            'winding_consistent': bool(source.is_winding_consistent), 'positive_volume': bool(source.volume > 0),
            'problem_faces': int(problem_faces(source).sum())}


def identify_regions(triangles, states):
    """Weld same-colour painted vertices; connected point contacts belong to one region."""
    keys = np.column_stack([np.round(triangles.reshape(-1, 3), 6), np.repeat(states, 3)])
    _, ids = np.unique(keys, axis=0, return_inverse=True)
    ids = ids.reshape(-1, 3)
    rows = np.concatenate([ids[:, 0], ids[:, 1], ids[:, 2]])
    cols = np.concatenate([ids[:, 1], ids[:, 2], ids[:, 0]])
    graph = coo_matrix((np.ones(len(rows), np.uint8), (rows, cols)), shape=(int(ids.max()) + 1,) * 2).tocsr()
    _, labels = connected_components(graph, directed=False)
    raw = labels[ids[:, 0]]
    unique, inverse = np.unique(raw, return_inverse=True)
    areas = trimesh.triangles.area(triangles)
    totals = np.bincount(inverse, weights=areas)
    # Associate sub-print-scale islands only with a nearby, substantially larger
    # region of the same filament. Geometry and colour ownership stay unchanged.
    island_limit, gap_limit = .5, .5
    associations = {}
    large = np.flatnonzero(totals > island_limit)
    for state in np.unique(states):
        targets = [int(i) for i in large if states[np.flatnonzero(inverse == i)[0]] == state]
        if not targets:
            continue
        target_mask = np.isin(inverse, targets)
        target_points = triangles[target_mask].reshape(-1, 3)
        target_owners = np.repeat(inverse[target_mask], 3)
        tree = cKDTree(target_points)
        small = np.flatnonzero((totals <= island_limit) & (totals > 0))
        for island in small:
            indices = np.flatnonzero(inverse == island)
            if states[indices[0]] != state:
                continue
            distances, nearest = tree.query(triangles[indices].reshape(-1, 3))
            candidate_owners = target_owners[nearest]
            eligible = (distances <= gap_limit) & (totals[candidate_owners] >= totals[island]*10)
            if not eligible.any():
                continue
            choice = np.flatnonzero(eligible)[np.argmin(distances[eligible])]
            associations[int(island)] = int(candidate_owners[choice])
    if associations:
        for island, target in associations.items():
            inverse[inverse == island] = target
        totals = np.bincount(inverse, weights=areas, minlength=len(totals))
    order = np.array([i for i in np.argsort(-totals) if totals[i] > 0])
    mapping = np.empty(len(totals), int)
    mapping[order] = np.arange(len(order))
    region_ids = mapping[inverse]
    regions = []
    for index, old in enumerate(order):
        selected = inverse == old
        state = int(states[np.flatnonzero(selected)[0]])
        points = triangles[selected].reshape(-1, 3)
        regions.append({'id': index, 'state': state, 'area': float(totals[old]),
                        'triangles': int(selected.sum()), 'grouped_islands': sum(target == int(old) for target in associations.values()),
                        'bounds': [points.min(0).tolist(), points.max(0).tolist()]})
    return region_ids, regions


def load_3mf(data: bytes, name='model.3mf'):
    if len(data) > 100 * 1024 * 1024:
        raise ValueError('This prototype accepts files up to 100 MB.')
    archive = zipfile.ZipFile(io.BytesIO(data))
    if sum(info.file_size for info in archive.infolist()) > 600 * 1024 * 1024:
        raise ValueError('Uncompressed project is too large for this prototype.')
    settings = json.loads(archive.read('Metadata/project_settings.config')) if 'Metadata/project_settings.config' in archive.namelist() else {}
    palette = list(settings.get('filament_colour', ['#849CBD']))
    default = 1
    if 'Metadata/model_settings.config' in archive.namelist():
        config = ET.fromstring(archive.read('Metadata/model_settings.config'))
        node = config.find('./object/metadata[@key="extruder"]')
        if node is not None:
            default = int(node.get('value', '1'))
    documents = {}

    def document(path):
        path = path.lstrip('/')
        if path not in documents:
            documents[path] = ET.fromstring(archive.read(path))
        return documents[path]

    roots = ET.fromstring(archive.read('_rels/.rels'))
    model_path = next((r.get('Target').lstrip('/') for r in roots if r.get('Type', '').endswith('/3dmodel')), '3D/3dmodel.model')
    top = document(model_path)
    if top.get('unit', 'millimeter') != 'millimeter':
        raise ValueError('Only millimetre 3MF projects are supported in this version.')
    found = []

    def walk(path, object_id, matrix, seen):
        key = (path, object_id)
        if key in seen:
            raise ValueError('Cyclic component reference.')
        obj = document(path).find(f'm:resources/m:object[@id="{object_id}"]', NS)
        if obj is None:
            raise ValueError('Missing mesh component.')
        mesh = obj.find('m:mesh', NS)
        if mesh is not None:
            found.append((mesh, matrix, path, object_id))
        for component in obj.findall('m:components/m:component', NS):
            target = component.get(PRODUCTION + 'path', path)
            target = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(posixpath.dirname(path), target)) if target != path else path
            walk(target, component.get('objectid'), matrix @ transform(component.get('transform')), seen | {key})

    for item in top.findall('m:build/m:item', NS):
        walk(model_path, item.get('objectid'), transform(item.get('transform')), set())
    if len(found) != 1:
        raise ValueError(f'This milestone supports one mesh instance; this project contains {len(found)}. Load the original painted single-mesh 3MF.')
    mesh, matrix, geometry_path, geometry_id = found[0]
    vertices = np.array([[float(v.get(k)) for k in 'xyz'] for v in mesh.findall('m:vertices/m:vertex', NS)])
    vertices = trimesh.transform_points(vertices, matrix)
    faces, painted, states, parents = [], [], [], []
    for triangle in mesh.findall('m:triangles/m:triangle', NS):
        face = [int(triangle.get(k)) for k in ['v1', 'v2', 'v3']]
        faces.append(face)
        leaves = decode_paint(vertices[face], triangle.get('paint_color', ''))
        for points, state in leaves:
            painted.append(points)
            states.append(default if state == 0 else state)
            parents.append(len(faces) - 1)
    source = trimesh.Trimesh(vertices, faces, process=False)
    triangles, states = np.array(painted), np.array(states, np.uint32)
    if len(triangles) > 2_000_000:
        raise ValueError('Paint subdivision exceeds the two-million-triangle prototype limit.')
    warnings = []
    if int(states.max()) > len(palette):
        raise ValueError('Paint references filament slots missing from the project palette.')
    region_ids, regions = identify_regions(triangles, states)
    warnings.append('Nearby same-colour islands up to 0.5 mm² are grouped within 0.5 mm of a region at least ten times larger. Paint and geometry are unchanged.')
    diagnostics = mesh_diagnostics(source)
    if not (source.is_watertight and source.is_winding_consistent and source.volume > 0):
        warnings.append('Inspection only: highlighted geometry needs review. Cutting is disabled until a valid repair is approved.')
    return PaintedModel(name, source, triangles, states, region_ids, regions, palette, settings, warnings,
                        diagnostics, np.array(parents, np.uint32),
                        {"data": data, "path": geometry_path, "object_id": geometry_id, "matrix": matrix,
                         "codes": [t.get("paint_color", "") for t in mesh.findall("m:triangles/m:triangle", NS)]})
