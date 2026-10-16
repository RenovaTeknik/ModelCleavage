from __future__ import annotations

from dataclasses import dataclass, replace
import math
import numpy as np
import manifold3d as mf
import trimesh
from shapely import union_all, set_precision
from shapely.geometry import Polygon

from .model import DIRECTIONS, PaintedModel, packed
from .progress import report


GEOMETRY_EPSILON = 1e-5


def prismatic_zones(source, direction, base_plane):
    """Intervals outboard of the attachment plane with genuinely parallel walls."""
    n = np.asarray(direction, float)
    projected = source.vertices @ n
    heights = projected[source.faces]
    levels = np.unique(np.r_[np.round(projected, 6), float(base_plane)])
    zones = []
    for low, high in zip(levels[:-1], levels[1:]):
        if low < base_plane - 1e-6 or high - low < .001:
            continue
        middle = (low + high) / 2
        active = (heights.min(1) < middle) & (heights.max(1) > middle)
        if active.any() and np.all(np.abs(source.face_normals[active] @ n) < 1e-7):
            # A source cap at an intermediate level can change the section
            # even when both neighbouring wall sets are parallel.
            zones.append((float(low), float(high)))
    return zones


def regularize_prismatic_sections(solid, source, n, u, v, base_plane):
    """Rebuild proven constant sections, excluding zero-volume Boolean fins."""
    zones = prismatic_zones(source, n, base_plane)
    if not zones:
        return solid, 0
    local = solid.transform(np.column_stack([np.array([u, v, n]), np.zeros(3)]).tolist())
    rebuilt_count = 0
    for low, high in zones:
        if local.is_empty():
            break
        section = local.slice((low + high) / 2)
        # Preserve geometry on both sides of the interval. Empty sections remove
        # unsupported sheets, rather than inventing a thickness for them.
        below = local.trim_by_plane([0, 0, -1], -low)
        above = local.trim_by_plane([0, 0, 1], high)
        rebuilt = section.extrude(high - low).translate([0, 0, low]) if not section.is_empty() else mf.Manifold()
        local = (below + rebuilt + above).simplify(1e-7)
        rebuilt_count += 1
    output = local.transform(np.column_stack([u, v, n, np.zeros(3)]).tolist())
    if output.status() != mf.Error.NoError:
        raise ValueError('The cut contains an unsupported zero-thickness edge. Change the pull direction or base plane.')
    return output, rebuilt_count


def assert_faces_bound_material(solid):
    """A closed triangle graph alone does not rule out attached zero-volume fins."""
    surface = mesh(solid)
    areas = surface.area_faces
    # Probe the broad faces most capable of forming visible unsupported planes.
    # Tiny triangulation edges are handled by section reconstruction/topology.
    candidates = np.flatnonzero(areas > .05)
    candidates = candidates[np.argsort(-areas[candidates])[:2048]]
    for index in candidates:
        normal = surface.face_normals[index]
        if not np.isfinite(normal).all() or np.linalg.norm(normal) < .5:
            raise ValueError('The cut contains a degenerate surface. No export was created.')
        centre = surface.triangles_center[index]
        inward = centre - normal * GEOMETRY_EPSILON
        # A point inside a solid has a forward exit as the first crossing. A
        # point on the back of an unsupported sheet has no interior interval.
        endpoint = inward + normal * max(float(np.linalg.norm(surface.extents)) * 2, 1.)
        hits = solid.ray_cast(inward.tolist(), endpoint.tolist())
        crossings = [h for h in hits if h.distance > 1e-12]
        if not crossings or np.dot(crossings[0].normal, normal) <= 0:
            raise ValueError('This cut leaves a zero-thickness sheet or an edge thinner than 0.00001 mm. Adjust the pull direction or base plane; no export was created.')


def assert_painted_surface_preserved(selected,part,source,tolerance=.0001,relief=None,seam_allowance=0):
    from .acceleration import SurfaceDistance
    points=np.unique(np.vstack([selected.reshape(-1,3),selected.mean(axis=1)]),axis=0)
    distances=SurfaceDistance(mesh(part).triangles)(points)
    eligible=np.ones(len(points),dtype=bool)
    failed=distances>tolerance
    if failed.any():
        # Source cleanup can remove microscopic shells before any cut. Those
        # discarded surfaces cannot be preserved as part of a printable solid.
        source_distances=SurfaceDistance(mesh(source).triangles)(points[failed])
        eligible[np.flatnonzero(failed)[source_distances>tolerance]]=False
    relieved=np.zeros(len(points),dtype=bool)
    if relief is not None and not relief.is_empty() and failed.any():
        relieved[failed]=SurfaceDistance(mesh(relief).triangles)(points[failed])<=tolerance
        eligible[relieved]=False
    fit_edges=np.zeros(len(points),dtype=bool)
    if seam_allowance and (failed&eligible).any():
        from .interface import paint_boundary
        vertices,edges=paint_boundary(selected)
        segments=vertices[edges];delta=segments[:,1]-segments[:,0]
        lengths=np.einsum('ij,ij->i',delta,delta)
        for index in np.flatnonzero(failed&eligible):
            if distances[index]>seam_allowance+tolerance:continue
            offset=points[index]-segments[:,0]
            t=np.clip(np.einsum('ij,ij->i',offset,delta)/lengths,0,1)
            seam_distance=np.linalg.norm(offset-t[:,None]*delta,axis=1).min()
            fit_edges[index]=seam_distance<=seam_allowance+tolerance
        eligible[fit_edges]=False
    maximum=float(distances[eligible].max()) if eligible.any() else 0.
    missing=int(((distances>tolerance)&eligible).sum())
    if missing:
        raise ValueError(f'The cut omits {missing} painted surface samples (maximum gap {maximum:.6g} mm). The complete selected feature must be preserved; no export was created.')
    return {'checked':True,'samples':int(len(points)),'excluded_source_cleanup_samples':int(((~eligible)&(~relieved)&(~fit_edges)).sum()),'excluded_numerical_relief_samples':int(relieved.sum()),'excluded_fit_seam_samples':int(fit_edges.sum()),
            'missing_samples':missing,'maximum_gap_mm':maximum,'tolerance_mm':tolerance}


def manifold(mesh):
    result = mf.Manifold(mf.Mesh64(vert_properties=np.asarray(mesh.vertices, np.float64), tri_verts=np.asarray(mesh.faces, np.uint64)))
    if result.status() != mf.Error.NoError:
        raise ValueError('The mesh could not be represented as a valid solid.')
    return result


def mesh(solid):
    output = solid.to_mesh64()
    return trimesh.Trimesh(np.array(output.vert_properties)[:, :3], np.array(output.tri_verts), process=False)


def polygon_contours(shape):
    contours = []
    for polygon in list(shape.geoms) if hasattr(shape, 'geoms') else [shape]:
        if polygon.is_empty or polygon.area < 1e-10:
            continue
        if polygon.geom_type != 'Polygon':
            continue
        contours.append(np.asarray(polygon.exterior.coords)[:-1])
        contours.extend(np.asarray(r.coords)[:-1] for r in polygon.interiors)
    return contours


@dataclass(frozen=True)
class CutParameters:
    region: int
    direction: str
    plane: float
    depth: float = 2.0
    side_clearance: float = 0.0
    depth_clearance: float = 0.0
    fastener: str = 'none'
    mode: str = 'planar'
    root_taper_degrees: float = 0.0
    root_smoothing_mm: float = 0.0
    minimum_fragment_width_mm: float = .2
    fit_target: str = 'body'
    glue_width_mm: float = 3.
    glue_length_mm: float = 1.5
    glue_depth_mm: float = .5
    glue_taper_degrees: float = 5.
    glue_wall_mm: float = .6

    def validate(self):
        if self.fit_target not in ['body','part','both']:raise ValueError('Choose body, excised part or both for the fit allowance.')
        if self.mode not in ['planar', 'interface']:
            raise ValueError('Choose a supported cut method.')
        if self.direction not in DIRECTIONS:
            raise ValueError('Choose one of the six supported pull directions.')
        if self.fastener not in ['none','glue']:
            raise ValueError('Choose a supported connection.')
        if self.fastener=='glue':
            if self.mode!='interface':raise ValueError('Glue keys require the paint-interface cut method.')
            values=[self.glue_width_mm,self.glue_length_mm,self.glue_depth_mm,self.glue_taper_degrees,self.glue_wall_mm]
            if not all(math.isfinite(x) for x in values):raise ValueError('Glue pocket settings must be finite numbers.')
            if not .5<=self.glue_width_mm<=20 or not .5<=self.glue_length_mm<=20 or not .1<=self.glue_depth_mm<=3 or not 1<=self.glue_taper_degrees<=15 or not .3<=self.glue_wall_mm<=3:
                raise ValueError('Use pocket openings 0.5–20 mm, depth 0.1–3 mm, taper 1–15°, and wall margin 0.3–3 mm.')
        if not all(math.isfinite(x) for x in [self.plane, self.depth, self.side_clearance, self.depth_clearance, self.root_taper_degrees, self.root_smoothing_mm, self.minimum_fragment_width_mm]):
            raise ValueError('Cut settings must be finite numbers.')
        if not 0 <= self.root_taper_degrees <= 15 or not 0 <= self.root_smoothing_mm <= .5:
            raise ValueError('Plug taper must be between 0 and 15 degrees; smoothing between 0 and 0.5 mm.')
        if not 0 <= self.minimum_fragment_width_mm <= 1:
            raise ValueError('Minimum fragment width must be between 0 and 1 mm.')
        if not .05 <= self.depth <= 100:
            raise ValueError('Depth must be between 0.05 and 100 mm.')
        if not 0 <= self.side_clearance <= 2 or not 0 <= self.depth_clearance <= 2:
            raise ValueError('Clearances must be between 0 and 2 mm.')


@dataclass
class CutResult:
    parameters: CutParameters
    extracted: mf.Manifold
    remainder: mf.Manifold
    nominal_remainder: mf.Manifold
    report: dict

    def payload(self):
        return {'part': packed(mesh(self.extracted).triangles), 'remainder': packed(mesh(self.remainder).triangles),
                'direction': DIRECTIONS[self.parameters.direction], 'report': self.report}


def clean_microscopic_components(solid, profile_resolution=None, detached_base_slivers=False):
    """Drop only bounded disconnected specks/cavity shells on the cut copy."""
    kept, removed = [], []
    for component in solid.decompose():
        volume = float(component.volume())
        bounds = np.asarray(component.bounding_box())
        extent = float(np.max(bounds[3:] - bounds[:3]))
        profile_speck = profile_resolution is not None and abs(volume) <= 6 * profile_resolution**3 and extent <= 5 * profile_resolution
        average_thickness=None
        numerical_sliver=False
        if detached_base_slivers and 1.<extent<=5. and abs(volume)<=1e-6:
            area=mesh(component).area
            average_thickness=float(2*abs(volume)/area) if area>0 else float('inf')
            numerical_sliver=bool(average_thickness<=.0001)
        if (abs(volume) <= .001 and extent <= 1.0) or profile_speck or numerical_sliver:
            removed.append({'signed_volume_mm3': volume, 'extent_mm': extent,
                            'bounds_mm': bounds.tolist(), 'detached_base_sliver':numerical_sliver,
                            'average_thickness_mm':average_thickness,
                            'action': 'filled cavity' if volume < 0 else 'removed speck'})
        else:
            kept.append(component)
    total = sum(abs(x['signed_volume_mm3']) for x in removed)
    allowance = .01 + (15 * profile_resolution**3 if profile_resolution is not None else 0)
    if total > allowance:
        raise ValueError(f'Tiny defects exceed the automatic cleanup allowance ({allowance:g} mm^3). Review the model repair.')
    if not kept:
        raise ValueError('This cut contains only microscopic fragments. Adjust the cut.')
    return (mf.Manifold.compose(kept) if removed else solid), removed


class InsertionCollision(ValueError):
    def __init__(self,report,part,base,intersection,display_components=None):
        super().__init__(f"The part collides with the body along the insertion path: {report['max_overlap_mm3']:.6g} mm³ overlap at {report['at_offset_mm']:.3g} mm travel (limit {report['tolerance_mm3']:.6g} mm³). No export was created.")
        self.collision_report=report
        self.part,self.base,self.intersection=part,base,intersection
        self.display_components=display_components

    def diagnostic_payload(self):
        return {'report':self.collision_report,'part':packed(mesh(self.part).triangles),
                'base':packed(mesh(self.base).triangles),'overlap':packed(np.concatenate([mesh(p).triangles for p in self.display_components]) if self.display_components else mesh(self.intersection).triangles)}


def check_insertion_path(part, base, direction, stroke, tolerance=.001):
    distances=sorted(set(min(stroke,d) for d in [.05,.2,.5,1.,2.,4.,8.,stroke/2,stroke] if d>0))
    overlaps=[];maximum=0.;worst=None;worst_part=None;worst_distance=0.
    for index,distance in enumerate(distances):
        report('Checking insertion path',index,len(distances))
        moved=part.translate((np.asarray(direction)*distance).tolist())
        intersection=moved ^ base
        volume=abs(float(intersection.volume()))
        overlaps.append(volume)
        if volume>maximum:
            maximum=volume;worst=intersection;worst_part=moved;worst_distance=distance
    if maximum>tolerance and worst_distance<=.2:
        # Failure diagnostics only: resolve the early-contact peak instead of
        # assuming the first coarse sample is the worst point of the motion.
        for distance in [.005,.01,.02,.03,.04,.06,.075,.1,.125,.15]:
            if distance>=stroke or distance in distances:continue
            moved=part.translate((np.asarray(direction)*distance).tolist())
            intersection=moved ^ base;volume=abs(float(intersection.volume()))
            distances.append(distance);overlaps.append(volume)
            if volume>maximum:
                maximum=volume;worst=intersection;worst_part=moved;worst_distance=distance
    if maximum>tolerance:
        surface=mesh(worst)
        pieces=sorted(worst.decompose(),key=lambda s:abs(s.volume()),reverse=True)
        significant=[p for p in pieces if abs(p.volume())>1e-10]
        contact_bounds=np.array([mesh(p).bounds for p in significant]) if significant else np.array([surface.bounds])
        bounds=np.array([contact_bounds[:,0].min(0),contact_bounds[:,1].max(0)])
        details={'max_overlap_mm3':maximum,'tolerance_mm3':tolerance,'at_offset_mm':worst_distance,
                 'direction':np.asarray(direction).tolist(),'bounds':bounds.tolist(),'raw_bounds':surface.bounds.tolist(),
                 'extent_mm':(bounds[1]-bounds[0]).tolist(),'samples':[{'offset_mm':d,'overlap_mm3':v} for d,v in sorted(zip(distances,overlaps))],
                 'component_count':len(significant),'raw_component_count':len(pieces),'display_volume_floor_mm3':1e-10,
                 'components':[{'volume_mm3':abs(float(p.volume())),'bounds':mesh(p).bounds.tolist()} for p in significant[:20]]}
        raise InsertionCollision(details,worst_part,base,worst,significant)
    return {'checked':True,'max_overlap_mm3':maximum,'offsets_mm':distances,'stroke_mm':stroke}


def interface_sweep_for_part(model,params,n,fit):
    from .interface import interface_sweep
    return interface_sweep(model.triangles[model.region_ids==params.region],n,params.depth,
                           model.triangles[model.region_ids!=params.region],0,params.root_taper_degrees,params.root_smoothing_mm,
                           params.depth,root_inset=fit['part_side_mm'],root_shortening=fit['part_depth_mm'])


def cut_region(model: PaintedModel, params: CutParameters):
    if not model.cut_ready:
        raise ValueError('Inspection-only model. Review and approve a valid repair before cutting.')
    report('Preparing cut')
    params.validate()
    requested_params=params
    fit_allowances={'minimum_mm':.05,'requested_side_mm':params.side_clearance,'requested_depth_mm':params.depth_clearance,
                    'effective_side_mm':max(.05,params.side_clearance),'effective_depth_mm':max(.05,params.depth_clearance)}
    body_fraction={'body':1.,'part':0.,'both':.5}[params.fit_target]
    fit_allowances.update(target=params.fit_target,body_side_mm=fit_allowances['effective_side_mm']*body_fraction,
                          part_side_mm=fit_allowances['effective_side_mm']*(1-body_fraction),body_depth_mm=fit_allowances['effective_depth_mm']*body_fraction,
                          part_depth_mm=fit_allowances['effective_depth_mm']*(1-body_fraction))
    params=replace(params,side_clearance=fit_allowances['body_side_mm'],depth_clearance=fit_allowances['body_depth_mm'])
    if not 0 <= params.region < len(model.regions):
        raise ValueError('Select a painted region first.')
    n = np.array(DIRECTIONS[params.direction], dtype=float)
    reference = np.eye(3)[int(np.argmin(abs(n)))]
    u = np.cross(reference, n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    selected = model.triangles[model.region_ids == params.region]
    flat = selected @ np.array([u, v]).T
    original_areas = trimesh.triangles.area(selected)
    heights = selected @ n
    is_base = heights.max(1) <= params.plane + GEOMETRY_EPSILON

    def projected_footprint(mask):
        polygons = []
        for triangle, area, included in zip(flat, original_areas, mask):
            if not included:
                continue
            polygon = Polygon(triangle)
            # Edge-on paint has no footprint. Do not inflate roundoff into a wall.
            if polygon.area > max(1e-9, area * 1e-7):
                polygons.append(set_precision(polygon, 1e-6))
        return union_all(polygons).buffer(.005, join_style=2).simplify(1e-5, preserve_topology=True) if polygons else None

    base_footprint = projected_footprint(is_base) if params.mode == 'planar' else None
    feature_footprint = projected_footprint(~is_base) if params.mode == 'planar' else None
    if params.mode == 'planar' and base_footprint is None and feature_footprint is None:
        raise ValueError('That region is edge-on to the pull direction. Choose another direction.')
    report('Preparing source solid')
    source, source_cleanup = clean_microscopic_components(manifold(model.source))
    limit = float((model.source.vertices @ n).max()) + 1

    interface_report = {}
    def cutter(side_gap, depth_gap):
        if params.mode == 'interface':
            from .interface import interface_sweep
            result, details = interface_sweep(selected, n, params.depth + depth_gap, model.triangles[model.region_ids != params.region], side_gap, params.root_taper_degrees, params.root_smoothing_mm, params.depth)
            if not (depth_gap or side_gap):
                interface_report.update(details)
            return result + nominal_cutter if (depth_gap or side_gap) else result

        bottom = params.plane - params.depth - depth_gap
        if bottom >= limit:
            raise ValueError('The base plane is beyond the model. Check its position.')
        pieces = []
        for footprint, top in [(base_footprint, params.plane + GEOMETRY_EPSILON * 2), (feature_footprint, limit)]:
            if footprint is None:
                continue
            outline = footprint.buffer(side_gap, join_style=2) if side_gap else footprint
            section = mf.CrossSection(polygon_contours(outline), mf.FillRule.EvenOdd)
            solid = section.extrude(top - bottom)
            pieces.append(solid.transform(np.column_stack([u, v, n, n * bottom]).tolist()))
        return mf.Manifold.batch_boolean(pieces, mf.OpType.Add)

    nominal_cutter = cutter(0, 0)
    report('Splitting model')
    extracted, nominal_remainder = source.split(nominal_cutter)
    if extracted.volume() < .001:
        raise ValueError('This cut produces no usable solid. Check the direction and base plane.')
    if nominal_remainder.volume() < .001:
        raise ValueError('This cut would remove the entire model. Choose a smaller region or adjust its base plane.')
    report('Applying fit allowances')
    remainder = nominal_remainder if not (params.side_clearance or params.depth_clearance) else source - cutter(params.side_clearance, params.depth_clearance)
    regularizer = regularize_prismatic_sections if params.mode == 'planar' else lambda solid, *args: (solid, 0)
    extracted, part_sections = regularizer(extracted, model.source, n, u, v, params.plane)
    nominal_remainder, base_sections = regularizer(nominal_remainder, model.source, n, u, v, params.plane)
    if params.side_clearance or params.depth_clearance:
        remainder, _ = regularizer(remainder, model.source, n, u, v, params.plane)
    else:
        remainder = nominal_remainder
    thin_fragments={'minimum_width_mm':params.minimum_fragment_width_mm,'nominal':[],'fit_only':[],'union_residues':[]}
    if params.mode=='interface' and params.minimum_fragment_width_mm:
        report('Checking cut-created thin fragments')
        from .printability import filter_cut_fragments,absorb_fragments
        nominal_remainder,fragments,thin_fragments['nominal']=filter_cut_fragments(nominal_remainder,source,params.minimum_fragment_width_mm)
        extracted,thin_fragments['union_residues']=absorb_fragments(extracted,fragments)
        if params.side_clearance or params.depth_clearance:
            remainder,_,thin_fragments['fit_only']=filter_cut_fragments(remainder,source,params.minimum_fragment_width_mm)
            # Enlarging the part by a nominal fragment must not cause an
            # overlap with its clearance pocket. Validation below checks this.
        else:remainder=nominal_remainder
    report('Cleaning microscopic defects')
    profile_resolution = None
    cleanup_allowance = .025 if profile_resolution is not None else .01
    extracted, part_cleanup = clean_microscopic_components(extracted, profile_resolution)
    nominal_remainder, nominal_cleanup = clean_microscopic_components(nominal_remainder, profile_resolution, detached_base_slivers=params.mode=='interface')
    if params.side_clearance or params.depth_clearance:
        remainder, base_cleanup = clean_microscopic_components(remainder, profile_resolution, detached_base_slivers=params.mode=='interface')
    else:
        remainder, base_cleanup = nominal_remainder, []
    cleanup = {'source': source_cleanup, 'part': part_cleanup, 'nominal_base': nominal_cleanup, 'base': base_cleanup}
    cleanup_volume = sum(abs(x['signed_volume_mm3']) for group in [part_cleanup, nominal_cleanup, base_cleanup] for x in group)
    if cleanup_volume > cleanup_allowance:
        raise ValueError('Cut artifacts exceed the automatic cleanup allowance. Review the cut.')
    if remainder.volume() < .001:
        raise ValueError('The clearance pocket removes the entire remaining model.')
    report('Checking closed solids')
    for solid in [extracted, remainder, nominal_remainder]:
        if solid.status() != mf.Error.NoError:
            raise ValueError('The cut produced invalid geometry. Try another direction or depth.')
        surface = mesh(solid)
        if not surface.is_watertight or not surface.is_winding_consistent:
            raise ValueError('The cut failed the closed-surface check.')
    report('Checking material thickness')
    assert_faces_bound_material(extracted)
    assert_faces_bound_material(remainder)
    paint_coverage={}
    if params.mode=='interface':
        report('Checking complete painted feature')
        paint_coverage=assert_painted_surface_preserved(selected,extracted,source)
    # Validate the nominal geometry independently of intended fit clearances.
    report('Checking recombination')
    reunited = extracted + nominal_remainder
    missing = abs((source - reunited).volume())
    excess = abs((reunited - source).volume())
    overlap = abs((extracted ^ remainder).volume())
    tolerance = max(.001, source.volume() * 1e-8) + cleanup_volume
    if max(missing, excess, overlap) > tolerance:
        raise ValueError('The cut failed recombination or overlap checks. No export was created.')
    if fit_allowances['part_side_mm'] or fit_allowances['part_depth_mm']:
        report('Applying part-side allowance')
        if params.depth<=fit_allowances['part_depth_mm']:raise ValueError('The part-side depth allowance consumes the hidden plug. Increase cut depth or reduce allowance.')
        if params.mode=='interface':
            contracted,_=interface_sweep_for_part(model,params,n,fit_allowances)
        else:
            contracted=cutter(-fit_allowances['part_side_mm'],-fit_allowances['part_depth_mm'])
            contracted=contracted+nominal_cutter.trim_by_plane(n.tolist(),params.plane)
        extracted=extracted^contracted
        retained=[p for p in extracted.decompose() if abs(p.volume())>1e-12]
        if not retained:raise ValueError('The part allowance leaves no usable material.')
        extracted=mf.Manifold.compose(retained).simplify(1e-7)
    relief_report={'width_mm':.05,'part':[],'body':[],'removed_volume_mm3':0.}
    numerical_relief=mf.Manifold()
    if params.mode=='interface':
        report('Relieving generated numerical skins')
        from .relief import relieve_prismatic_skins
        extracted,part_relief,relief_report['part']=relieve_prismatic_skins(extracted,model.source,n,interface_report['cap_plane']+fit_allowances['part_depth_mm'])
        remainder,body_relief,relief_report['body']=relieve_prismatic_skins(remainder,model.source,n,interface_report['cap_plane']-fit_allowances['body_depth_mm'])
        extracted=mf.Manifold.compose([p for p in extracted.decompose() if abs(p.volume())>1e-12]).simplify(1e-7)
        remainder=mf.Manifold.compose([p for p in remainder.decompose() if abs(p.volume())>1e-12]).simplify(1e-7)
        before_part,before_body=extracted,remainder
        extracted,post_part_cleanup=clean_microscopic_components(extracted)
        remainder,post_body_cleanup=clean_microscopic_components(remainder)
        cleanup['post_fit_part']=post_part_cleanup;cleanup['post_fit_body']=post_body_cleanup
        if sum(abs(x['signed_volume_mm3']) for key,group in cleanup.items() if key!='source' for x in group)>.01:
            raise ValueError('Post-fit artifacts exceed the bounded cleanup allowance. Review this cut.')
        part_relief=part_relief+(before_part-extracted)
        body_relief=body_relief+(before_body-remainder)
        numerical_relief=part_relief+body_relief
        relief_report['removed_volume_mm3']=float(numerical_relief.volume())
        paint_coverage=assert_painted_surface_preserved(selected,extracted,source,relief=part_relief,seam_allowance=fit_allowances['part_side_mm'])
        for label,solid in [('part',extracted),('body',remainder)]:
            surface=mesh(solid)
            if solid.status()!=mf.Error.NoError or not surface.is_watertight or not surface.is_winding_consistent:raise ValueError('Fit or skin relief failed the closed-solid check.')
            try:assert_faces_bound_material(solid)
            except ValueError as error:raise ValueError(f'After skin relief ({label}): {error}') from error
    glue_report={'enabled':False,'total_removed_mm3':0.}
    if params.fastener=='glue':
        report('Adding paired glue keys')
        from .glue import glue_pockets
        extracted,remainder,glue_report=glue_pockets(extracted,remainder,n,interface_report['cap_plane'],params,part_depth_gap=fit_allowances['part_depth_mm'])
        for solid in [extracted,remainder]:
            surface=mesh(solid)
            if not surface.is_watertight or not surface.is_winding_consistent:raise ValueError('A glue pocket failed the closed-solid check.')
            assert_faces_bound_material(solid)
        paint_coverage=assert_painted_surface_preserved(selected,extracted,source,relief=part_relief,seam_allowance=fit_allowances['part_side_mm'])
        if abs((extracted^remainder).volume())>tolerance:raise ValueError('Glue-pocket geometry failed overlap checks.')
    overlap=abs((extracted^remainder).volume())
    if overlap>tolerance:raise ValueError('The final fitted parts overlap. No export was created.')
    # Disconnected cavity shells cannot safely be exported as independent printable parts.
    counts = {}
    for name, solid in [('part', extracted), ('base', remainder)]:
        components = solid.decompose()
        if any(p.volume() <= .001 for p in components):
            raise ValueError(f'The final {name} contains a cavity or fragment beyond bounded cleanup limits. Review the cut or allowance.')
        counts[name] = len(components)
    removed_for_fit = max(0., float(source.volume() - extracted.volume() - remainder.volume() - glue_report['total_removed_mm3'] - relief_report['removed_volume_mm3'])) if (fit_allowances['effective_side_mm'] or fit_allowances['effective_depth_mm']) else 0.
    insertion_path = {}
    if params.mode == 'interface':
        stroke=float(np.ptp(model.source.vertices@n))+params.depth+1
        insertion_path=check_insertion_path(extracted,remainder,n,stroke)
    warnings = ['Interface outline simplified with 0.02 mm tolerance. The root has straight sides along the insertion direction. Review the seam and choose fit allowance before printing.' if params.mode == 'interface' else 'Directional projection can change side colour boundaries. Review the separated part before printing.']
    if relief_report['removed_volume_mm3']>1e-9:
        warnings.append('Generated numerical skins below 0.05 mm were relieved on the cut copy. Affected paint samples and removed volume are recorded in the report.')
    if glue_report['enabled']:
        warnings.append('Paired undercut glue recesses added to the hidden flat mating faces. Apply adhesive to both pockets before assembly.')
    if thin_fragments['nominal'] or thin_fragments['fit_only']:
        warnings.append(f"Minimum-width filter joined {len(thin_fragments['nominal'])} thin body fragment(s) to the removable part; removed {len(thin_fragments['fit_only'])} thin fragment(s) from the clearance pocket. See measured widths in the report.")
    if any(cleanup.values()):
        warnings.append('Automatically removed microscopic specks or filled tiny cavities on the cut copy. Details are included in the export report.')
    if counts['part'] > 1:
        warnings.append(f'The selected surface produces {counts["part"]} separate solid pieces in this direction.')
    if counts['base'] > 1:
        warnings.append(f'The remaining body separates into {counts["base"]} solids.')
    return CutResult(requested_params, extracted, remainder, nominal_remainder, {
        'numerical_skin_relief':relief_report, 'fit_allowances':fit_allowances, 'glue_keys':glue_report, 'thin_fragment_filter':thin_fragments, 'closed': True, 'painted_surface_coverage':paint_coverage, 'nominal_recombination': True, 'cut_mode': params.mode, 'interface': interface_report, 'insertion_path': insertion_path, 'automatic_cleanup': cleanup,
        'cleanup_limits': {'component_volume_mm3': .001, 'component_extent_mm': 1., 'total_volume_mm3': cleanup_allowance, 'detached_base_sliver_volume_mm3':1e-6 if params.mode=='interface' else None, 'detached_base_sliver_thickness_mm':.0001 if params.mode=='interface' else None, 'detached_base_sliver_extent_mm':5. if params.mode=='interface' else None, 'profile_speck_volume_mm3': .006 if profile_resolution else None, 'profile_speck_extent_mm': .5 if profile_resolution else None},
        'border_smoothing': model.diagnostics.get('border_smoothing'),
        'source_cleanup_absolute_mm3': sum(abs(x['signed_volume_mm3']) for x in source_cleanup), 'missing_mm3': missing, 'excess_mm3': excess,
        'overlap_mm3': overlap, 'fit_gap_volume_mm3': removed_for_fit,
        'part_volume_mm3': float(extracted.volume()), 'base_volume_mm3': float(remainder.volume()),
        'part_pieces': counts['part'], 'base_pieces': counts['base'],
        'surface_material_checked': True, 'regularized_sections': part_sections + base_sections,
        'material_probe_face_limit': 2048, 'geometry_resolution_mm': GEOMETRY_EPSILON,
        'boundary_regularization_mm': .005, 'warnings': warnings,
        'clearance_definition': 'Side clearance is per side and depth clearance is axial. Each has a 0.05 mm minimum total effective value, including when zero is requested. Target body enlarges the cavity, target part reduces the hidden plug, and both splits each gap equally. Numerical skin relief is recorded separately.'})
