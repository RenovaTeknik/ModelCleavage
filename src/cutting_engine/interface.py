import numpy as np
from scipy.spatial import cKDTree
from .progress import report
from .model import triangle_normals


def paint_boundary(triangles):
    vertices, inverse = np.unique(np.round(triangles.reshape(-1,3),7),axis=0,return_inverse=True)
    tree=cKDTree(vertices)
    faces=inverse.reshape(-1,3)
    edges=np.concatenate([faces[:,[0,1]],faces[:,[1,2]],faces[:,[2,0]]])
    unique, counts=np.unique(np.sort(edges,axis=1),axis=0,return_counts=True)
    # Adaptive paint uses T junctions: split unmatched coarse edges at all existing vertices.
    pieces=[]
    for (a,b),count in zip(unique,counts):
        if count==2: continue
        start,end=vertices[a],vertices[b];delta=end-start;length=np.linalg.norm(delta)
        if length<1e-8: continue
        candidates=np.array(tree.query_ball_point((start+end)/2,length/2+1e-6),dtype=int)
        t=(vertices[candidates]-start)@delta/(length*length)
        distance=np.linalg.norm(vertices[candidates]-start-t[:,None]*delta,axis=1)
        ids=candidates[(distance<2e-6)&(t>=-1e-7)&(t<=1+1e-7)]
        ids=ids[np.argsort((vertices[ids]-start)@delta)]
        pieces.extend([tuple(sorted((int(x),int(y)))) for x,y in zip(ids[:-1],ids[1:]) for _ in range(int(count)) if x!=y])
    unique,counts=np.unique(pieces,axis=0,return_counts=True)
    # Subdivided/overlapping paint can contribute the same segment more
    # than twice. Paired incidences cancel; every odd remainder is boundary.
    # Keeping only count==1 drops triple incidences and invents open gaps.
    boundary=unique[counts%2==1]
    return vertices,boundary



def close_boundary_gaps(vertices,edges,triangles,tolerance=.05):
    """Repair only short open boundary gaps supported by the painted surface."""
    from .acceleration import SurfaceDistance
    degree=np.bincount(edges.ravel(),minlength=len(vertices))
    odd=list(np.flatnonzero(degree%2));bridges=[];lengths=[]
    if len(odd)>128:raise ValueError('The painted boundary has too many open junctions to form a reliable solid profile.')
    distance_to_surface=SurfaceDistance(triangles) if odd else None
    while odd:
        distance,a,b=min((float(np.linalg.norm(vertices[a]-vertices[b])),int(a),int(b)) for j,a in enumerate(odd) for b in odd[j+1:])
        if distance>tolerance or sum(lengths)+distance>.25:
            raise ValueError('The painted boundary has an open gap too large to close safely. No solid cut was created.')
        samples=vertices[a]+np.array([.25,.5,.75])[:,None]*(vertices[b]-vertices[a])
        if float(distance_to_surface(samples).max())>.005:
            raise ValueError('An open paint-boundary gap leaves the painted surface. No solid cut was created.')
        bridges.append((a,b));lengths.append(distance);odd.remove(a);odd.remove(b)
    return (np.vstack([edges,bridges]) if bridges else edges),{'count':len(bridges),'lengths_mm':lengths,'maximum_gap_mm':tolerance,'total_limit_mm':.25}


def interface_sweep(selected, n, depth, surrounding=None, side_gap=0, taper_degrees=0, smoothing_mm=0, nominal_depth=None, root_inset=0, root_shortening=0):
    """A constant painted profile swept along a single assembly direction.

    The cavity extends outward beyond the source. Its constant cross-section
    makes every intermediate rigid withdrawal position free of the base.
    """
    import manifold3d as mf
    from shapely import union_all, set_precision
    from shapely.geometry import Polygon, LineString
    from shapely.ops import polygonize
    from .engine import polygon_contours
    report('Finding paint boundary')
    vertices, edges=paint_boundary(selected)
    if not len(edges):raise ValueError('The selected paint has no interface boundary.')
    boundary_repairs={'count':0,'lengths_mm':[],'maximum_gap_mm':.05,'total_limit_mm':.25}
    reference=np.eye(3)[np.argmin(abs(n))]
    u=np.cross(reference,n);u/=np.linalg.norm(u);v=np.cross(n,u)
    projected=selected@np.array([u,v]).T
    report('Building interface profile')
    polygons=[]
    for triangle in projected:
        polygon=Polygon(triangle)
        if polygon.area>1e-9:polygons.append(set_precision(polygon,1e-6))
    if not polygons:raise ValueError('This painted area is edge-on. Choose another insertion direction.')
    original=union_all(polygons)
    # Close only sub-0.1 mm notches, preserving holes and the complete paint
    # footprint. The small outward guard avoids coplanar Boolean fins.
    radius=.05
    smooth=original.buffer(radius,quad_segs=4).buffer(-radius,quad_segs=4)
    profile=union_all([original,smooth]).buffer(.005,join_style=2)
    boundary_height=float((vertices[np.unique(edges)]@n).min())
    boundary_xy=vertices@np.array([u,v]).T
    lines=[LineString(boundary_xy[edge]) for edge in edges if np.linalg.norm(boundary_xy[edge[1]]-boundary_xy[edge[0]])>1e-7]
    regions=list(polygonize(union_all(lines)))
    interface_profile=union_all(regions).intersection(original)
    if interface_profile.area<original.area*.01:
        # Dangling fragments can coexist with an already sound outer loop.
        # Repair gaps only when the usable filled profile has collapsed.
        edges,boundary_repairs=close_boundary_gaps(vertices,edges,selected)
        lines=[LineString(boundary_xy[edge]) for edge in edges if np.linalg.norm(boundary_xy[edge[1]]-boundary_xy[edge[0]])>1e-7]
        regions=list(polygonize(union_all(lines)))
        interface_profile=union_all(regions).intersection(original)
    if interface_profile.is_empty:raise ValueError('The painted interface could not form a closed profile in this direction.')
    raw_interface_profile=interface_profile
    # Keep small grouped islands when simplifying; otherwise a disappearing
    # island can make the boundary jump far beyond the requested tolerance.
    interface_profile=interface_profile.simplify(.02,preserve_topology=True).buffer(.005,join_style=2).intersection(profile)
    def outer_curves(shape):
        return union_all([polygon.exterior for polygon in shape.geoms]) if hasattr(shape,'geoms') else shape.exterior
    outline_deviation=float(outer_curves(raw_interface_profile).hausdorff_distance(outer_curves(interface_profile)))
    if outline_deviation>.15:
        for simplify in [.01,.005,.001,0.]:
            for guard in [.005,.001,0.]:
                candidate=raw_interface_profile.simplify(simplify,preserve_topology=True).buffer(guard,join_style=2) if guard else raw_interface_profile.simplify(simplify,preserve_topology=True)
                candidate=candidate.intersection(profile)
                deviation=float(outer_curves(raw_interface_profile).hausdorff_distance(outer_curves(candidate)))
                if deviation<=.15:
                    interface_profile=candidate;outline_deviation=deviation;break
            if outline_deviation<=.15:break
        else:raise ValueError('The projected interface outline changes by more than 0.15 mm. Choose another insertion direction.')
    if interface_profile.area<original.area*.01:
        raise ValueError('The attachment profile collapsed to less than 1% of the painted footprint. A shell-like cut was rejected.')
    protected_plane=None
    shared_bottom=None
    if abs(float(n[2]))<1e-8 and surrounding is not None and len(surrounding):
        bottom_z=float(min(selected[:,:,2].min(),surrounding[:,:,2].min()))
        import trimesh
        coplanar_tolerance=.005
        selected_flat=(np.max(np.abs(selected[:,:,2]-bottom_z),axis=1)<=coplanar_tolerance)&(triangle_normals(selected)[:,2]<-.995)
        body_flat=(np.max(np.abs(surrounding[:,:,2]-bottom_z),axis=1)<=coplanar_tolerance)&(triangle_normals(surrounding)[:,2]<-.995)
        if trimesh.triangles.area(selected[selected_flat]).sum()>.01 and trimesh.triangles.area(surrounding[body_flat]).sum()>.01:
            axis=np.array([u[2],v[2]])
            c=float((np.vstack(polygon_contours(interface_profile))@axis).min())
            if abs(c-bottom_z)<=coplanar_tolerance+.005+1e-8:
                protected_plane=(axis,c)
                shared_bottom=bottom_z
    if protected_plane is not None:
        # Flatten only the micron-scale underside noise before mirroring the
        # profile. Otherwise mirrored near-coplanar edges enclose tiny slots,
        # which can produce an undercut lip when lofted.
        from shapely.ops import transform as transform_shape
        axis,c=protected_plane
        def flatten_floor(x,y,z=None):
            points=np.column_stack([x,y]);height=points@axis
            shift=np.where(height<=c+.015,c-height,0.)
            changed=points+shift[:,None]*axis
            return changed[:,0],changed[:,1]
        interface_profile=transform_shape(flatten_floor,interface_profile).buffer(0)
    attachment_profile=interface_profile
    smoothing_deviation=0.
    if smoothing_mm:
        before=interface_profile
        from .root_profile import protected_profile
        extended,clip=protected_profile(before,protected_plane)
        interface_profile=extended.buffer(smoothing_mm,quad_segs=8).buffer(-2*smoothing_mm,quad_segs=8).buffer(smoothing_mm,quad_segs=8)
        if clip is not None:interface_profile=interface_profile.intersection(clip)
        if interface_profile.is_empty:raise ValueError('Smoothing removes the plug profile. Reduce smoothing.')
        interface_profile=interface_profile.simplify(min(.005,smoothing_mm/10),preserve_topology=True)
        smoothing_deviation=float(before.boundary.hausdorff_distance(interface_profile.boundary))
    if root_inset:
        from .root_profile import inward_profile
        interface_profile=inward_profile(interface_profile,root_inset,protected_plane)
        if interface_profile.is_empty:raise ValueError('The part-side allowance consumes the plug. Reduce the allowance or increase plug size.')
    nominal_profile=interface_profile
    if side_gap:
        profile=profile.buffer(side_gap,join_style=2)
        interface_profile=interface_profile.buffer(side_gap,join_style=2).intersection(profile)
    bottom=boundary_height-depth
    all_points=selected.reshape(-1,3)
    if surrounding is not None and len(surrounding):all_points=np.vstack([all_points,surrounding.reshape(-1,3)])
    top=float((all_points@n).max())+1
    from .root_profile import tapered_root
    if taper_degrees:
        from .seam_root import seam_root
        from .root_profile import inward_profile
        mouth_profile=inward_profile(attachment_profile,root_inset,protected_plane) if root_inset else attachment_profile
        root,root_details=seam_root(mouth_profile,vertices[edges],n,u,v,boundary_height-(nominal_depth if nominal_depth is not None else depth),bottom,taper_degrees,side_gap,protected_plane,top=top,smoothing=smoothing_mm)
    else:
        root,root_details=tapered_root(nominal_profile,boundary_height,top,nominal_depth if nominal_depth is not None else depth,depth,0,side_gap,protected_plane)
        root_details['full_mating_span_mm']=nominal_depth if nominal_depth is not None else depth
    if root_shortening:root=root.trim_by_plane([0,0,1],boundary_height-depth+root_shortening)
    # Preserve the established attachment shoulder outboard of the mating
    # plane. Shape changes belong to the hidden plug, not the visible feature
    # or its escape envelope; the shoulder may grow only in the pull direction.
    shoulder=attachment_profile.buffer(side_gap,join_style=2) if side_gap else attachment_profile
    shoulder_solid=mf.CrossSection(polygon_contours(shoulder),mf.FillRule.EvenOdd).extrude(top-boundary_height).translate([0,0,boundary_height])
    # An unmodified shoulder would restore nominal width above the lowest
    # point of an organic seam, producing a step partway along the plug.
    # For part-side clearance the inset root continues to the actual painted
    # surface sweep, which alone restores the visible feature.
    if not (root_inset or taper_degrees):root=root+shoulder_solid
    # Sweep every painted triangle all the way outward. Using only the first
    # front-facing hit loses a returning curl behind the attachment plane.
    # Triangle prisms are convex; their union is the exact directional envelope
    # of the full painted surface, with no bounding-box or sampled-depth clip.
    report('Sweeping complete painted feature')
    local_triangles=selected@np.array([u,v,n]).T
    pieces=[]
    prism_faces=np.array([[2,1,0],[3,4,5],[0,1,4],[0,4,3],
                          [1,2,5],[1,5,4],[2,0,3],[2,3,5]],dtype=np.uint64)
    guard=.005
    sweep_gap=side_gap+guard
    if sweep_gap:
        angles=np.arange(16)*2*np.pi/16
        radius=sweep_gap/np.cos(np.pi/16)
        offsets=np.column_stack([radius*np.cos(angles),radius*np.sin(angles),np.zeros(16)])
    determinants=np.cross(local_triangles[:,1]-local_triangles[:,0],local_triangles[:,2]-local_triangles[:,0])[:,2]
    edge_on=np.abs(determinants)<1e-12
    edge_sweep_count=0
    if int(edge_on.sum())>32 and sweep_gap:
        from .edge_sweep import planar_edge_sweeps
        slabs=planar_edge_sweeps(local_triangles[edge_on],top,sweep_gap)
        pieces.extend(slabs);edge_sweep_count=len(slabs)
        sweep_triangles=local_triangles[~edge_on]
    else:sweep_triangles=local_triangles
    for index,triangle in enumerate(sweep_triangles):
        if index%128==0:report('Sweeping complete painted feature',index,len(local_triangles))
        a,b,c=triangle
        determinant=(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        # Edge-on painted side walls still belong to the feature. The small
        # transverse guard gives their sweep a valid solid width.
        if abs(determinant)<1e-12 and not sweep_gap:continue
        if determinant<0:triangle=triangle[[0,2,1]]
        lower=triangle.copy();lower[:,2]-=guard
        upper=triangle.copy();upper[:,2]=top
        points=np.vstack([lower,upper])
        if sweep_gap:
            piece=mf.Manifold.hull_points((points[:,None,:]+offsets[None,:,:]).reshape(-1,3))
        else:
            piece=mf.Manifold(mf.Mesh64(vert_properties=np.array(points,dtype=np.float64,order='C'),tri_verts=prism_faces))
        if piece.status()!=mf.Error.NoError:
            raise ValueError('A painted triangle could not form a valid full-feature sweep.')
        pieces.append(piece)
    if not pieces:raise ValueError('The painted feature is edge-on to this insertion direction.')
    report('Combining complete feature sweep')
    front=mf.Manifold.batch_boolean(pieces,mf.OpType.Add)
    solid=root+front
    solid=solid.transform(np.column_stack([u,v,n,np.zeros(3)]).tolist())
    return solid,{'boundary_gap_repairs':boundary_repairs,'method':'complete painted surface sweep with flat root cap','cap_plane':bottom,
                  'deepest_interface':bottom+depth,'boundary_segments':len(edges),
                  'profile_coordinate_precision_mm':.000001, 'interface_outline_deviation_mm':outline_deviation,
                  'side_clearance_mm':side_gap,'profile_coverage_guard_mm':.005,
                  'profile_smoothing_radius_mm':.02,'root_smoothing_mm':smoothing_mm,'root_smoothing_deviation_mm':smoothing_deviation,'root_taper_degrees':taper_degrees,'root_tip':root_details,'shared_bottom_plane_mm':shared_bottom,'shared_bottom_preserved':protected_plane is not None,'shared_bottom_detection_tolerance_mm':.005,'constant_cross_section':taper_degrees==0, 'outward_expanding_profile':True,
                  'interface_profile_area_mm2':float(interface_profile.area), 'feature_shoulder_plane':boundary_height,
                  'local_junction_limited':True,'full_painted_surface_sweep':True,'swept_triangle_count':len(local_triangles),'edge_on_triangle_count':int(edge_on.sum()),'edge_on_planar_sweeps':edge_sweep_count,
                  'feature_sampling_mm':None,'side_clearance_polygon_sides':16,'feature_coverage_guard_mm':guard,
                  'profile_area_mm2':float(profile.area),'original_profile_area_mm2':float(original.area),
                  'missing_paint_profile_area_mm2':float(original.difference(profile).area),
                  'paint_boundary_constrained':True,'extraction_limit':top}
