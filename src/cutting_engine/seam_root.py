"""Drafted mating walls anchored to the actual three-dimensional paint seam."""
import math
import numpy as np
import manifold3d as mf
from shapely.geometry import Polygon,Point
from shapely import union_all
from .root_profile import contours


def seam_root(profile,boundary,n,u,v,nominal_bottom,bottom,angle,side_gap=0,protected_plane=None,top=None,smoothing=0):
    if protected_plane is not None:
        from .root_profile import protected_profile
        axis,c=protected_plane;axis=np.asarray(axis)
        extended,_=protected_profile(profile,protected_plane)
        local=boundary@np.array([u,v,n]).T
        local[:,:,:2]-=2*(local[:,:,:2]@axis-c)[:,:,None]*axis
        reflected=local@np.array([u,v,n])
        solid,details=seam_root(extended,np.concatenate([boundary,reflected]),n,u,v,nominal_bottom,bottom,angle,side_gap,None,top,smoothing)
        solid=solid.trim_by_plane([float(axis[0]),float(axis[1]),0.],float(c-side_gap))
        details['protected_bottom']=True
        return solid,details
    if side_gap:profile=profile.buffer(side_gap,join_style=2)
    raw=boundary@np.array([u,v,n]).T
    delta=raw[:,1,:2]-raw[:,0,:2];lengths=(delta*delta).sum(1)
    raw=raw[lengths>1e-14];delta=delta[lengths>1e-14];lengths=lengths[lengths>1e-14]
    if not len(raw):raise ValueError('The paint seam has no usable projected edges.')
    slope=math.tan(math.radians(angle));rings=[];heights=[];bands=[]
    for ring in contours(profile):
        dense=[]
        for a,b in zip(ring,np.roll(ring,-1,axis=0)):
            count=max(1,int(math.ceil(np.linalg.norm(b-a)/.5)))
            dense.extend(a+(b-a)*i/count for i in range(count))
        ring=np.asarray(dense);h=[]
        for point in ring:
            t=np.clip(((point-raw[:,0,:2])*delta).sum(1)/lengths,0,1)
            distance=((point-raw[:,0,:2]-t[:,None]*delta)**2).sum(1)
            closest=int(np.argmin(distance));h.append(raw[closest,0,2]+t[closest]*(raw[closest,1,2]-raw[closest,0,2]))
        h=np.asarray(h)
        if float(h.min())<=nominal_bottom:raise ValueError('The plug cap must lie behind the complete paint seam.')
        edge=np.roll(ring,-1,axis=0)-ring;edge_length=np.linalg.norm(edge,axis=1);tangent=edge/edge_length[:,None]
        inward=np.column_stack([-tangent[:,1],tangent[:,0]])
        distances=slope*(h-nominal_bottom)
        for i,a in enumerate(ring):
            j=(i+1)%len(ring);b=ring[j]
            bands.append(Polygon([a,b,b+inward[i]*distances[j],a+inward[i]*distances[i]]))
            bands.append(Point(a).buffer(float(distances[i]),quad_segs=8))
        rings.append(ring);heights.append(h)
    # Erode by the local draft depth along every seam segment. Subtracting
    # the complete boundary band resolves concave corners and vanishing
    # fillets without leaving the reversed offset loops of a raw miter loft.
    tip_shape=profile.difference(union_all(bands))
    if tip_shape.is_empty or tip_shape.area<1e-8:raise ValueError('The taper consumes the plug tip. Reduce taper or depth.')
    if smoothing:
        tip_shape=tip_shape.intersection(tip_shape.buffer(smoothing,quad_segs=8).buffer(-2*smoothing,quad_segs=8).buffer(smoothing,quad_segs=8))
    tip_shape=tip_shape.intersection(profile.buffer(-.00001,join_style=2)).simplify(.000001,preserve_topology=True).buffer(0)
    if tip_shape.is_empty:raise ValueError('The taper consumes the plug tip. Reduce taper or depth.')
    tip_rings=contours(tip_shape);annulus=profile.difference(tip_shape)
    vertices=[];faces=[];registry={}
    def height(point):
        t=np.clip(((point-raw[:,0,:2])*delta).sum(1)/lengths,0,1)
        distance=((point-raw[:,0,:2]-t[:,None]*delta)**2).sum(1)
        closest=int(np.argmin(distance))
        return float(raw[closest,0,2]+t[closest]*(raw[closest,1,2]-raw[closest,0,2]))
    def vertex(point,z):
        key=(round(float(point[0]),10),round(float(point[1]),10),round(float(z),10))
        if key not in registry:registry[key]=len(vertices);vertices.append([float(point[0]),float(point[1]),float(z)])
        return registry[key]
    def surface(rings,z_function,reverse=False):
        if not rings:return
        points=np.vstack(rings);ids=[vertex(point,z_function(point)) for point in points]
        for face in mf.triangulate(rings):
            triangle=[ids[int(i)] for i in face]
            faces.append(triangle[::-1] if reverse else triangle)
    wall_rings=contours(annulus)
    top=float(top if top is not None else max(h.max() for h in heights)+1)
    surface(wall_rings,lambda point:top)
    surface(tip_rings,lambda point:top)
    for ring in wall_rings:
        for a,b in zip(ring,np.roll(ring,-1,axis=0)):
            if profile.boundary.distance(Point(a))>1e-7 or profile.boundary.distance(Point(b))>1e-7:continue
            ta,tb=vertex(a,top),vertex(b,top)
            ma,mb=vertex(a,height(a)),vertex(b,height(b))
            faces.extend([[ta,ma,mb],[ta,mb,tb]])
    surface(tip_rings,lambda point:nominal_bottom,True)
    surface(wall_rings,lambda point:nominal_bottom if tip_shape.boundary.distance(Point(point))<1e-7 else height(point),True)
    solid=mf.Manifold(mf.Mesh64(np.asarray(vertices,dtype=np.float64),np.asarray(faces,dtype=np.uint64)))
    if solid.status()!=mf.Error.NoError:raise ValueError('The drafted paint seam could not form a closed plug.')
    if bottom<nominal_bottom:
        extension=mf.CrossSection(tip_rings,mf.FillRule.EvenOdd).extrude(nominal_bottom-bottom).translate([0,0,bottom])
        solid=solid+extension
    span=float(max(h.max() for h in heights)-nominal_bottom)
    return solid,{'seam_anchored':True,'full_mating_span_mm':span,'tip_inset_mm':span*slope,'tip_area_mm2':float(tip_shape.area),'taper_sections':1,'tip_construction_guard_mm':.00001,'mouth_follows_paint_boundary':True,'extra_depth_has_constant_tip_section':bool(bottom<nominal_bottom)}
