"""Directional sweeps of coplanar edge-on paint without thousands of 3D unions."""
import numpy as np
import manifold3d as mf
from shapely import union_all,set_precision
from shapely.geometry import Polygon
from .engine import polygon_contours


def planar_edge_sweeps(triangles,top,guard):
    groups={}
    for triangle in triangles:
        normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]);length=np.linalg.norm(normal[:2])
        if length<1e-14:continue
        normal=np.r_[normal[:2]/length,0.]
        if normal[np.argmax(abs(normal[:2]))]<0:normal=-normal
        offset=float(triangle.mean(0)@normal)
        key=tuple(np.round(normal[:2],7))+(round(offset,6),)
        groups.setdefault(key,[]).append(triangle)
    solids=[]
    for key,group in groups.items():
        m=np.array([key[0],key[1],0.]);m/=np.linalg.norm(m);p=np.array([-m[1],m[0],0.]);n=np.array([0.,0.,1.])
        group=np.asarray(group);offset=float((group@m).mean())
        projected=group@np.array([p,n]).T
        patches=[set_precision(Polygon(t),1e-7) for t in projected if Polygon(t).area>1e-14]
        patch=union_all(patches).simplify(1e-7,preserve_topology=True)
        regions=list(patch.geoms) if hasattr(patch,'geoms') else [patch]
        envelopes=[patch]
        for region in regions:
            if region.is_empty or region.geom_type!='Polygon':continue
            points=np.asarray(region.exterior.coords)
            for a,b in zip(points[:-1],points[1:]):
                if abs(a[0]-b[0])<1e-12:continue
                poly=Polygon([a,b,[b[0],top],[a[0],top]])
                if poly.area>1e-14:envelopes.append(poly)
        shape=union_all(envelopes).buffer(guard,join_style=2)
        if shape.is_empty:continue
        slab=mf.CrossSection(polygon_contours(shape),mf.FillRule.EvenOdd).extrude(2*guard)
        solids.append(slab.transform(np.column_stack([p,n,m,m*(offset-guard)]).tolist()))
    return solids
