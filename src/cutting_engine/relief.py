"""Bounded relief of generated thin skins in proven prismatic source zones."""
import numpy as np
import manifold3d as mf
from .engine import prismatic_zones,polygon_contours
from shapely import set_precision,union_all
from functools import reduce
from shapely.geometry import Polygon


def relieve_prismatic_skins(solid,source,n,mouth,width=.05):
    reference=np.eye(3)[np.argmin(abs(n))];u=np.cross(reference,n);u/=np.linalg.norm(u);v=np.cross(n,u)
    rotation=np.array([u,v,n]);local=solid.transform(np.column_stack([rotation,np.zeros(3)]).tolist())
    source_solid=mf.Manifold(mf.Mesh64(np.array(source.vertices,dtype=float),np.array(source.faces,dtype=np.uint64)))
    original=source_solid.transform(np.column_stack([rotation,np.zeros(3)]).tolist())
    removed=[];records=[]
    def planar(section):
        rings=[]
        for ring in section.to_polygons():
            polygon=Polygon(ring)
            if polygon.area>1e-10:rings.append(set_precision(polygon.buffer(0),1e-6))
        return reduce(lambda a,b:a.symmetric_difference(b),rings,Polygon()).simplify(2e-6,preserve_topology=True)
    def opened(shape):return shape.buffer(-width/2,join_style=2).buffer(width/2,join_style=2)
    for low,high in prismatic_zones(source,n,mouth):
        candidates=[]
        for level in [low+min(1e-4,(high-low)/10),(low+high)/2,high-min(1e-4,(high-low)/10)]:
            section=planar(local.slice(level))
            if not section.is_empty:candidates.append(section.difference(opened(section)))
        thin=union_all(candidates)
        if thin.is_empty or thin.area<1e-9:continue
        source_section=planar(original.slice((low+high)/2))
        # Step past the coincident skin boundary so subtraction cannot leave
        # a numerically closed film on the old plane.
        thin=thin.buffer(.0001,join_style=2)
        intrinsic=source_section.difference(opened(source_section))
        # Floating point opening can leave area-free traces along healthy
        # source edges. Buffering those would protect generated skins.
        intrinsic=union_all([p for p in getattr(intrinsic,'geoms',[intrinsic]) if p.area>1e-8])
        if not intrinsic.is_empty:thin=thin.difference(intrinsic.buffer(width,join_style=2))
        if thin.is_empty or thin.area<1e-9:continue
        if thin.buffer(-width/2,join_style=2).area>1e-8:
            raise ValueError('A generated skin exceeds the 0.05 mm relief limit. Review the cut.')
        mask=mf.CrossSection(polygon_contours(thin),mf.FillRule.EvenOdd).extrude(high-low+.0002).translate([0,0,low-.0001])
        lost=local^mask
        if lost.volume()<=1e-10:continue
        changed=local-mask
        if len([c for c in changed.decompose() if c.volume()>.001])>len([c for c in local.decompose() if c.volume()>.001]):
            raise ValueError('Skin relief would separate a meaningful part. Review the cut.')
        local=changed.simplify(1e-7);removed.append(lost)
        records.append({'axis_interval_mm':[low,high],'removed_volume_mm3':float(lost.volume()),'maximum_cross_section_width_mm':width})
    transform=np.column_stack([u,v,n,np.zeros(3)]).tolist()
    relief=mf.Manifold.batch_boolean(removed,mf.OpType.Add).transform(transform) if removed else mf.Manifold()
    return local.transform(transform),relief,records
