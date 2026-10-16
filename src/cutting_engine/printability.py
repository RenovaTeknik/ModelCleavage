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
