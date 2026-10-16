from dataclasses import dataclass
import numpy as np
import trimesh
from .engine import manifold, mesh
from .model import PaintedModel, identify_regions, mesh_diagnostics, packed


@dataclass
class RepairProposal:
    candidate: PaintedModel
    report: dict
    removed: np.ndarray

    def payload(self):
        return {'report': self.report, 'positions': packed(self.candidate.source.triangles),
                'changed_positions': packed(self.removed)}


def triangle_key(triangle):
    return tuple(sorted(tuple(float(x) for x in row) for row in np.round(triangle, 8)))


def propose_repair(model):
    if model.cut_ready:
        raise ValueError('This mesh already passes the solid-topology checks.')
    if model.paint_parents is None:
        raise ValueError('Paint-to-source mapping is unavailable; this repair cannot safely preserve paint.')
    repaired = mesh(manifold(model.source))
    if not repaired.is_watertight or not repaired.is_winding_consistent or repaired.volume <= 0:
        raise ValueError('Automatic normalization did not produce a valid solid. The original remains unchanged.')
    source_keys = {}
    for index, triangle in enumerate(model.source.triangles):
        key = triangle_key(triangle)
        if key in source_keys:
            raise ValueError('Coincident faces have ambiguous paint ownership. Automatic repair is unavailable; use an external mesh repair tool.')
        source_keys[key] = index
    export_faces = []
    retained = set()
    flips = set()
    new_triangles = []
    for triangle in repaired.triangles:
        index = source_keys.get(triangle_key(triangle))
        export_faces.append(index)
        if index is None:
            new_triangles.append(triangle)
            continue
        original = model.source.triangles[index]
        # The kernel may split shared vertices, but retained face coordinates must remain unchanged.
        a = np.array(sorted(map(tuple, triangle)))
        b = np.array(sorted(map(tuple, original)))
        if not np.allclose(a, b, rtol=0, atol=1e-8):
            raise ValueError('This repair moves painted geometry; exact paint preservation cannot be verified.')
        retained.add(index)
        if np.dot(np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0]), np.cross(original[1]-original[0], original[2]-original[0])) < 0:
            flips.add(index)
    keep = np.isin(model.paint_parents, list(retained))
    triangles = model.triangles[keep].copy()
    if flips:
        reverse = np.isin(model.paint_parents[keep], list(flips))
        triangles[reverse] = triangles[reverse][:, [0, 2, 1]]
    states = model.states[keep].copy()
    positions_by_original={}
    for new_id,old_id in enumerate(export_faces):
        if old_id is not None:positions_by_original.setdefault(old_id,[]).append(new_id)
    parents=np.array([positions_by_original[int(i)][0] for i in model.paint_parents[keep]],dtype=np.uint32)
    # Normalization can retain the same geometric face in multiple topological
    # positions. Keep paint leaves for every resulting face, not just its key.
    from collections import Counter
    for index, count in Counter(i for i in export_faces if i is not None).items():
        if count > 1:
            leaves = model.triangles[model.paint_parents == index].copy()
            if index in flips:
                leaves = leaves[:, [0, 2, 1]]
            triangles = np.concatenate([triangles] + [leaves] * (count-1))
            states = np.concatenate([states] + [model.states[model.paint_parents == index]] * (count-1))
            parents=np.concatenate([parents]+[np.full(len(leaves),i,dtype=np.uint32) for i in positions_by_original[index][1:]])
    if new_triangles:
        new_triangles = np.array(new_triangles)
        painted_mesh = trimesh.Trimesh(model.triangles.reshape(-1, 3), np.arange(len(model.triangles)*3).reshape(-1, 3), process=False)
        _, distances, nearest = trimesh.proximity.closest_point(painted_mesh, new_triangles.mean(1))
        triangles = np.concatenate([triangles, new_triangles])
        states = np.r_[states, model.states[nearest]]
        parents=np.r_[parents,np.array([i for i,j in enumerate(export_faces) if j is None],dtype=np.uint32)]
    ids, regions = identify_regions(triangles, states)
    warnings = [w for w in model.warnings if not w.startswith('Inspection only:')]
    warnings.append('User-approved topology repair is active in memory; the source file is unchanged.')
    candidate = PaintedModel(model.name, repaired, triangles, states, ids, regions, model.palette,
                             model.settings, warnings, mesh_diagnostics(repaired), parents)
    if model.archive_source is not None:
        codes = []
        faces = repaired.faces.copy()
        new_index = 0
        for i, original_index in enumerate(export_faces):
            if original_index is None:
                state = int(states[len(states)-len(new_triangles)+new_index])
                code = encode_uniform_state(state)
                new_index += 1
            else:
                code = model.archive_source['codes'][original_index]
                if original_index in flips:
                    # Uniform paint is independent of triangle corner order.
                    leaves = model.states[model.paint_parents == original_index]
                    if len(set(leaves.tolist())) > 1:
                        code = None
                    else:
                        code = encode_uniform_state(int(leaves[0]))
                else:
                    original = model.source.triangles[original_index]
                    permutation = [int(np.argmin(np.linalg.norm(repaired.triangles[i]-v, axis=1))) for v in original]
                    faces[i] = faces[i][permutation]
            codes.append(code)
        candidate.archive_source = model.archive_source
        candidate.repair_export = {'faces': faces, 'codes': codes}
    removed = model.source.triangles[~np.isin(np.arange(len(model.source.faces)), list(retained))]
    report = {'before_triangles': len(model.source.faces), 'after_triangles': len(repaired.faces),
              'removed_triangles': len(removed), 'before_volume_mm3': float(model.source.volume),
              'after_volume_mm3': float(repaired.volume), 'surface_area_change_mm2': float(repaired.area-model.source.area),
              'paint_preserved_on_retained_faces': True, 'removed_painted_leaves': int((~keep).sum()),
              'new_surfaces': len(new_triangles), 'approximated_colour_faces': len(new_triangles), 'cut_ready': candidate.cut_ready,
              'note': 'Retained faces preserve exact paint. Changed faces use the nearest original painted surface colour at their centre; fine paint boundaries on those faces may change. Approval applies only to this in-memory working copy. The source file is never overwritten.'}
    return RepairProposal(candidate, report, removed)


def encode_uniform_state(state):
    if state < 3:
        return format(state << 2, 'X')
    if state < 18:
        return format(state-3, 'X') + 'C'
    return format(state-18, 'X') + 'FC'
