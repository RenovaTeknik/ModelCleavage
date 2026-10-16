"""Paired shallow undercut glue pockets on hidden flat mating faces."""
import math
import numpy as np
import manifold3d as mf
from shapely import union_all
from shapely.geometry import Polygon
from shapely.affinity import translate
from .engine import mesh


def frustum(width,length,depth,angle,u,v,direction,origin,start=0.):
    slope=math.tan(math.radians(angle))
    vertices=[]
    for z in [start,depth]:
        x=width/2+z*slope;y=length/2+z*slope
        vertices.extend([[-x,-y,z],[x,-y,z],[x,y,z],[-x,y,z]])
    faces=np.array([[0,2,1],[0,3,2],[4,5,6],[4,6,7],
                    [0,1,5],[0,5,4],[1,2,6],[1,6,5],
                    [2,3,7],[2,7,6],[3,0,4],[3,4,7]],dtype=np.uint64)
    solid=mf.Manifold(mf.Mesh64(np.array(vertices,dtype=float),faces))
    return solid.transform(np.column_stack([u,v,direction,origin]).tolist())


def flat_face(solid,n,level,u,v):
    surface=mesh(solid);tri=surface.triangles
    match=np.max(np.abs(tri@n-level),axis=1)<2e-5
    projected=tri[match]@np.array([u,v]).T
    shapes=[Polygon(t) for t in projected if abs((t[1,0]-t[0,0])*(t[2,1]-t[0,1])-(t[1,1]-t[0,1])*(t[2,0]-t[0,0]))>1e-10]
    return union_all(shapes)


def glue_pockets(part,base,n,cap,params,part_depth_gap=0):
    reference=np.eye(3)[np.argmin(abs(n))];u=np.cross(reference,n);u/=np.linalg.norm(u);v=np.cross(n,u)
    body_cap=cap-params.depth_clearance
    part_cap=cap+part_depth_gap
    common=flat_face(part,n,part_cap,u,v).intersection(flat_face(base,n,body_cap,u,v))
    width=params.glue_width_mm;length=params.glue_length_mm;depth=params.glue_depth_mm;angle=params.glue_taper_degrees;wall=params.glue_wall_mm
    if common.is_empty:raise ValueError('No shared flat mating face is available for glue pockets.')
    slope=math.tan(math.radians(angle));pad=wall/math.cos(math.radians(angle))
    halfx=width/2+(depth+wall)*slope+pad;halfy=length/2+(depth+wall)*slope+pad
    candidates=common
    # Fast conservative candidate screening. The solid envelope test below
    # also checks holes, concavities and material behind both flat faces.
    for x,y in [(-halfx,-halfy),(-halfx,halfy),(halfx,-halfy),(halfx,halfy),(0,-halfy),(0,halfy),(-halfx,0),(halfx,0)]:
        candidates=candidates.intersection(translate(common,xoff=-x,yoff=-y))
    if candidates.is_empty:raise ValueError('Glue pockets do not fit this mating face with the requested wall margin. Reduce their size, depth or margin.')
    shapes=sorted(list(candidates.geoms) if hasattr(candidates,'geoms') else [candidates],key=lambda p:p.area,reverse=True)
    points=[]
    for shape in shapes[:4]:
        for point in [shape.representative_point(),shape.centroid]:
            if candidates.covers(point):points.append(np.array(point.coords[0]))
    lo=np.array(candidates.bounds[:2]);hi=np.array(candidates.bounds[2:])
    from shapely.geometry import Point
    for x in np.linspace(lo[0],hi[0],7):
        for y in np.linspace(lo[1],hi[1],7):
            if candidates.covers(Point(x,y)):points.append(np.array([x,y]))
    chosen=None
    for xy in points:
        origins=[u*xy[0]+v*xy[1]+n*level for level in [part_cap,body_cap]]
        safe=True
        for solid,direction,origin in zip([part,base],[n,-n],origins):
            envelope=frustum(width+2*pad,length+2*pad,depth+wall,angle,u,v,direction,origin,start=1e-4)
            if abs((envelope-solid).volume())>max(1e-7,envelope.volume()*1e-8):safe=False;break
        if safe:chosen=origins;break
    if chosen is None:raise ValueError('There is not enough material behind both mating faces for these glue pockets. Reduce their size or depth.')
    cutters=[frustum(width,length,depth,angle,u,v,direction,origin,start=-1e-4) for direction,origin in zip([n,-n],chosen)]
    outputs=[part-cutters[0],base-cutters[1]]
    removed=[float(a.volume()-b.volume()) for a,b in zip([part,base],outputs)]
    expected=width*length*depth+(width+length)*slope*depth**2+4/3*slope*slope*depth**3
    for old,new,volume in zip([part,base],outputs,removed):
        if new.status()!=mf.Error.NoError or len(new.decompose())!=len(old.decompose()) or abs(volume-expected)>max(1e-6,expected*1e-6):
            raise ValueError('A glue pocket failed its open-recess or solid-continuity check. No export was created.')
    return *outputs,{'enabled':True,'pairs':1,'opening_mm':[width,length],'interior_mm':[width+2*depth*slope,length+2*depth*slope],
                      'depth_each_mm':depth,'undercut_degrees':angle,'wall_margin_mm':wall,'wall_envelope_checked':True,
                      'opening_centres_mm':[p.tolist() for p in chosen],'axis':n.tolist(),'removed_volume_mm3':removed,'total_removed_mm3':sum(removed),
                      'opening_gap_mm':params.depth_clearance+part_depth_gap,'nominal_volume_each_mm3':expected}
