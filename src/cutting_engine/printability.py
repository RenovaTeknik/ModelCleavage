"""Conservative filtering of detached, cut-created body fragments."""
import numpy as np
import manifold3d as mf
from .engine import mesh


def filter_cut_fragments(base, source, minimum_width):
    if minimum_width<=0:return base,[],[]
    components=base.decompose()
    if len(components)<2:return base,[],[]
    source_small=[c for c in source.decompose() if 0<c.volume()<=5]
    kept=[];fragments=[];records=[]
    largest=max(range(len(components)),key=lambda i:components[i].volume())
    for i,c in enumerate(components):
        volume=float(c.volume());bounds=np.array(c.bounding_box());extent=float(max(bounds[3:]-bounds[:3]))
        if i==largest or not 1e-9<volume<=5 or extent>20:
            kept.append(c);continue
        # An existing separate feature is not a cut artifact.
        if any(abs(float(old.volume())-volume)<=max(1e-8,volume*1e-6) and np.allclose(old.bounding_box(),bounds,atol=1e-6,rtol=0) for old in source_small):
            kept.append(c);continue
        surface=mesh(c)
        width=float(min(bounds[3:]-bounds[:3]))
        if width>=minimum_width:
            try:width=float(min(surface.bounding_box_oriented.primitive.extents))
            except (ValueError,RuntimeError):
                kept.append(c);continue
        # Both an enclosing width and surface/volume thinness must agree.
        thickness=2*volume/float(surface.area)
        if width>=minimum_width or thickness>=minimum_width:
            kept.append(c);continue
        fragments.append(c)
        records.append({'volume_mm3':volume,'enclosing_width_mm':width,'mean_thickness_mm':thickness,'extent_mm':extent,'bounds_mm':bounds.tolist()})
    if sum(r['volume_mm3'] for r in records)>5:
        raise ValueError('Thin cut fragments exceed 5 mm³. Review this cut before exporting.')
    return (mf.Manifold.compose(kept) if fragments else base),fragments,records


def absorb_fragments(part,fragments):
    if not fragments:return part,[]
    combined=mf.Manifold.batch_boolean([part]+fragments,mf.OpType.Add)
    kept=[];zero=[]
    for c in combined.decompose():
        if abs(float(c.volume()))<=1e-12:
            zero.append({'signed_volume_mm3':float(c.volume()),'action':'removed zero-volume union residue'})
        else:kept.append(c)
    if not kept or combined.status()!=mf.Error.NoError:
        raise ValueError('Thin fragments could not be joined safely to the removable part.')
    result=mf.Manifold.compose(kept) if zero else combined
    if len(result.decompose())>len(part.decompose()):
        raise ValueError('A thin body fragment cannot join the removable part. Review the cut or disable the minimum-width filter.')
    return result,zero


def painted_speck_bridge(part, source, selected, direction):
    """Bounded, source-clipped escape envelopes for cut-created painted specks."""
    from .acceleration import SurfaceDistance
    from .engine import polygon_contours
    from shapely.geometry import MultiPoint
    import trimesh
    components=part.decompose()
    if len(components)<2:return None,[]
    main=max(components,key=lambda c:c.volume())
    surface=mesh(main)
    paint=SurfaceDistance(selected)
    n=np.asarray(direction,dtype=float)
    reference=np.eye(3)[np.argmin(abs(n))]
    u=np.cross(reference,n);u/=np.linalg.norm(u);v=np.cross(n,u)
    envelopes=[];records=[]
    for component in components:
        volume=float(component.volume());bounds=np.asarray(component.bounding_box())
        if component is main or not 0<volume<=.001 or max(bounds[3:]-bounds[:3])>1:continue
        vertices=mesh(component).vertices
        if paint(vertices).min()>.0001:continue
        centre=vertices.mean(0)
        closest,distance,_=trimesh.proximity.closest_point_naive(surface,centre[None,:])
        gap=float(distance[0])
        if gap>.5:continue
        points=np.vstack([vertices,closest])
        profile=MultiPoint(points@np.array([u,v]).T).convex_hull.buffer(.1,quad_segs=4)
        bottom=float((points@n).min())-.1
        # Signed directions require all eight bounding-box corners for the top.
        box=np.asarray(source.bounding_box()).reshape(2,3)
        top=float(sum(box[1,i]*n[i] if n[i]>=0 else box[0,i]*n[i] for i in range(3)))+1
        envelope=mf.CrossSection(polygon_contours(profile),mf.FillRule.EvenOdd).extrude(top-bottom).translate([0,0,bottom])
        envelope=envelope.transform(np.column_stack([u,v,n,np.zeros(3)]).tolist())
        addition=(source^envelope)-part
        if addition.volume()>.1:continue
        joined=part+addition
        if sum(c.volume()>.001 for c in joined.decompose())!=sum(c.volume()>.001 for c in part.decompose()):continue
        # Require the speck's painted vertices to reach the main solid, rather
        # than merely increasing the size of another disconnected island.
        largest=max(joined.decompose(),key=lambda c:c.volume())
        if abs((component-largest).volume())>1e-10:continue
        envelopes.append(envelope)
        records.append({'speck_volume_mm3':volume,'bridge_material_mm3':float(addition.volume()),'gap_mm':gap,'profile_guard_mm':.1,'maximum_gap_mm':.5,'maximum_material_mm3':.1})
    if sum(r['bridge_material_mm3'] for r in records)>.2:
        raise ValueError('Painted sliver bridges exceed the bounded repair allowance. Review the painted boundary.')
    return (mf.Manifold.batch_boolean(envelopes,mf.OpType.Add) if envelopes else None),records
