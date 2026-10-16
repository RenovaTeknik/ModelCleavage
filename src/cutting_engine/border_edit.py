"""Bounded shared-mesh deformation driven by a selected paint boundary."""
from copy import deepcopy
import numpy as np
import trimesh
from scipy.spatial import cKDTree
from .interface import paint_boundary


def smooth_border(model, region, amount=.15, band=1.0):
    if not model.cut_ready: raise ValueError('Repair the mesh before smoothing.')
    if not 0 <= region < len(model.regions): raise ValueError('Invalid region.')
    if not np.isfinite([amount,band]).all() or not 0 < amount <= .5 or not .1 <= band <= 5:
        raise ValueError('Use movement above 0 and up to 0.5 mm, and a band between 0.1 and 5 mm.')
    if model.paint_parents is None: raise ValueError('Paint parent mapping is unavailable.')
    points,edges=paint_boundary(model.triangles[model.region_ids==region])
    degree=np.bincount(edges.ravel(),minlength=len(points))
    sums=np.zeros_like(points)
    np.add.at(sums,edges[:,0],points[edges[:,1]])
    np.add.at(sums,edges[:,1],points[edges[:,0]])
    delta=np.divide(sums,degree[:,None],out=points.copy(),where=degree[:,None]>0)-points
    delta[degree!=2]=0 # Preserve open ends and ambiguous junctions.
    lengths=np.linalg.norm(delta,axis=1)
    delta*=np.minimum(1,amount/np.maximum(lengths,1e-15))[:,None]
    ids=np.unique(edges)
    distance,nearest=cKDTree(points[ids]).query(model.source.vertices)
    motion=delta[ids[nearest]]*(np.maximum(0,1-distance/band)**2)[:,None]
    normals=model.source.vertex_normals
    motion-=normals*np.sum(motion*normals,axis=1)[:,None] # Tangential relaxation.
    fixed=np.zeros(len(motion),bool)
    sharp=model.source.face_adjacency_edges[model.source.face_adjacency_angles>np.deg2rad(50)]
    fixed[sharp.ravel()]=True
    fixed |= model.source.vertices[:,2] <= model.source.bounds[0,2]+.005
    motion[fixed]=0
    # Barycentric interpolation keeps every paint subdivision on its parent
    # face and keeps both colours coincident along shared edges.
    old=model.source.triangles[model.paint_parents]
    bary=np.stack([trimesh.triangles.points_to_barycentric(old,model.triangles[:,i]) for i in range(3)],axis=1)
    if np.max(np.abs(np.einsum('nki,nij->nkj',bary,old)-model.triangles))>1e-5:
        raise ValueError('Paint mapping needs repair before this mesh can be edited.')
    candidate=deepcopy(model)
    scale=1.
    for attempt in range(9):
        candidate.source.vertices=np.asarray(model.source.vertices)+motion*scale
        new=candidate.source.triangles
        dot=np.sum(candidate.source.face_normals*model.source.face_normals,axis=1)
        valid_area=candidate.source.area_faces>=np.minimum(model.source.area_faces*.25,1e-12)
        if candidate.cut_ready and np.all(dot>.5) and np.all(valid_area):break
        scale*=.5
    else:raise ValueError('This adjustment folds a face. Reduce movement or widen the band.')
    motion*=scale
    candidate.triangles=np.einsum('nki,nij->nkj',bary,new[model.paint_parents])
    for r in candidate.regions:
        triangles=candidate.triangles[candidate.region_ids==r['id']]
        r['area']=float(trimesh.triangles.area(triangles).sum())
        r['bounds']=[triangles.reshape(-1,3).min(0).tolist(),triangles.reshape(-1,3).max(0).tolist()]
    # Old archive coordinates must never masquerade as the edited source.
    candidate.archive_source=None; candidate.repair_export=None
    candidate.diagnostics.pop('repair_approval',None)
    report={'maximum_movement_mm':float(np.linalg.norm(motion,axis=1).max()),
            'moved_vertices':int((np.linalg.norm(motion,axis=1)>1e-9).sum()),
            'safety_scale':scale,'movement_limit_mm':amount,'band_mm':band,'region':region}
    candidate.diagnostics['border_smoothing']=report
    return candidate,report
