"""Nested normal-offset root sections: narrower toward the hidden end."""
import math
import numpy as np
import manifold3d as mf
from shapely import union_all
from shapely.geometry.polygon import orient
from .progress import report


def contours(shape):
    result=[]
    for polygon in list(shape.geoms) if hasattr(shape,'geoms') else [shape]:
        if polygon.is_empty or polygon.geom_type!='Polygon':continue
        polygon=orient(polygon,sign=1.)
        result.append(np.asarray(polygon.exterior.coords)[:-1])
        result.extend(np.asarray(r.coords)[:-1] for r in polygon.interiors)
    return result


def protected_profile(shape,plane):
    if plane is None:return shape,None
    from shapely.affinity import affine_transform
    from shapely.geometry import Polygon
    a=np.asarray(plane[0],float);c=float(plane[1]);b=np.array([-a[1],a[0]])
    matrix=[1-2*a[0]*a[0],-2*a[0]*a[1],-2*a[0]*a[1],1-2*a[1]*a[1],2*c*a[0],2*c*a[1]]
    extended=union_all([shape,affine_transform(shape,matrix)])
    points=np.vstack(contours(shape));along=points@a;across=points@b
    margin=max(1.,float(np.ptp(points,axis=0).max()))*4
    lo=float(across.min())-margin;hi=float(across.max())+margin;far=float(along.max())+margin
    clip=Polygon([a*c+b*lo,a*far+b*lo,a*far+b*hi,a*c+b*hi])
    return extended,clip


def inward_profile(shape,inset,plane=None):
    if inset==0:return shape
    extended,clip=protected_profile(shape,plane)
    result=extended.buffer(-inset,join_style=2)
    return result.intersection(clip) if clip is not None else result


def tapered_root(profile,mouth,top,depth,total_depth,angle,side_gap=0,protected_plane=None):
    slope=math.tan(math.radians(angle))
    inset=depth*slope
    if inset<1e-8:
        shape=profile.buffer(side_gap,join_style=2) if side_gap else profile
        return mf.CrossSection(contours(shape),mf.FillRule.EvenOdd).extrude(top-(mouth-total_depth)).translate([0,0,mouth-total_depth]),{'tip_inset_mm':0.,'taper_sections':0,'tip_area_mm2':float(profile.area)}
    if protected_plane is not None:
        # Loft the mirrored profile first, then trim at the protected plane.
        # This creates a true vertical shared-bottom wall without coincident
        # section edges or T junctions in the loft's side triangulation.
        extended,_=protected_profile(profile,protected_plane)
        solid,details=tapered_root(extended,mouth,top,depth,total_depth,angle,side_gap,None)
        a=np.asarray(protected_plane[0],float);c=float(protected_plane[1])
        solid=solid.trim_by_plane([float(a[0]),float(a[1]),0.],c-side_gap)
        details['tip_area_mm2']=float(inward_profile(profile,inset,protected_plane).area)
        details['protected_bottom']=True
        return solid,details
    if side_gap:
        profile=profile.buffer(side_gap,join_style=2)
        side_gap=0
    tip=inward_profile(profile,inset,protected_plane)
    if tip.is_empty or tip.area<1e-8:
        raise ValueError('The taper consumes the plug tip. Reduce the taper angle or depth.')
    count=max(1,int(math.ceil(inset/.025)))
    if count>512:raise ValueError('This taper needs too many sections. Reduce its angle or depth.')
    levels=[]
    for i in range(count+1):
        shape=profile if i==0 else inward_profile(profile,inset*i/count,protected_plane)
        if shape.is_empty:raise ValueError('The taper pinches off the plug. Reduce the taper angle.')
        if side_gap:shape=shape.buffer(side_gap,join_style=2)
        levels.append(shape)
    vertices=[];faces=[];registry={}
    def vertex(xy,z):
        key=(round(float(xy[0]),10),round(float(xy[1]),10),round(float(z),10))
        if key not in registry:
            registry[key]=len(vertices);vertices.append([float(xy[0]),float(xy[1]),float(z)])
        return registry[key]
    def cap(shape,z,reverse=False):
        rings=contours(shape)
        points=np.vstack(rings);ids=[vertex(p,z) for p in points]
        for face in mf.triangulate(rings):
            face=[ids[int(i)] for i in face]
            faces.append(face[::-1] if reverse else face)
    cap(levels[0],mouth)
    cap(levels[-1],mouth-depth,True)
    for i,(outer,inner) in enumerate(zip(levels[:-1],levels[1:])):
        report('Building tapered plug',i,count)
        ztop=mouth-depth*i/count;zbottom=mouth-depth*(i+1)/count
        annulus=outer.difference(inner)
        rings=contours(annulus)
        if not rings:continue
        inner_keys={tuple(np.round(p,10)) for ring in contours(inner) for p in ring}
        outer_keys={tuple(np.round(p,10)) for ring in contours(outer) for p in ring}
        points=np.vstack(rings);ids=[]
        for p in points:
            key=tuple(np.round(p,10))
            if key in inner_keys:z=zbottom
            elif key in outer_keys:z=ztop
            else:
                from shapely.geometry import Point
                z=zbottom if inner.boundary.distance(Point(p))<outer.boundary.distance(Point(p)) else ztop
            ids.append(vertex(p,z))
        for face in mf.triangulate(rings):faces.append([ids[int(j)] for j in face][::-1])
    solid=mf.Manifold(mf.Mesh64(vert_properties=np.array(vertices,dtype=np.float64),tri_verts=np.array(faces,dtype=np.uint64)))
    if solid.status()!=mf.Error.NoError:
        raise ValueError('The tapered profile could not form a closed plug. Reduce smoothing or the taper angle.')
    upper=mf.CrossSection(contours(levels[0]),mf.FillRule.EvenOdd).extrude(top-mouth).translate([0,0,mouth])
    solid=solid+upper
    extra=total_depth-depth
    if extra>1e-9:
        extension=mf.CrossSection(contours(levels[-1]),mf.FillRule.EvenOdd).extrude(extra).translate([0,0,mouth-total_depth])
        solid=solid+extension
    return solid,{'tip_inset_mm':float(inset),'taper_sections':count,'tip_area_mm2':float(tip.area),'extra_depth_has_constant_tip_section':bool(extra>1e-9)}
