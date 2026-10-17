"""Accepted cuts and paint-preserving working bodies for a multi-part assembly."""
from dataclasses import dataclass,asdict
import copy,uuid
import numpy as np
from .engine import mesh,manifold,clean_microscopic_components
from .model import PaintedModel,packed,DIRECTIONS
from .acceleration import SurfaceDistance


def part_name(value):
    value=str(value).strip()
    if not value or len(value)>80 or any(ord(c)<32 for c in value):
        raise ValueError('Use a part name of 1–80 characters without control characters.')
    return value


def check_existing_sockets(model,result):
    history=getattr(model,'socket_history',[])
    if hasattr(result,'report'):result.report['existing_socket_check']={'checked':True,'socket_count':len(history),'surface_tolerance_mm':.0001,'changed_area_limit_mm2':.01}
    if not history:return
    distance=SurfaceDistance(mesh(result.remainder).triangles)
    for socket in history:
        triangles=socket['triangles']
        samples=np.concatenate([triangles,triangles.mean(1)[:,None,:]],axis=1)
        moved=distance(samples.reshape(-1,3)).reshape(-1,4).max(1)>.0001
        area=np.linalg.norm(np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]),axis=1)/2
        if float(area[moved].sum())>.01:
            raise ValueError(f'This cut would alter the existing socket for "{socket["name"]}". Undo that cut or choose a different direction or depth.')


def remaining_model(model,result):
    """Keep exact paint only for intact regions; source faces supply grey backing/context."""
    source=mesh(result.remainder)
    distance=SurfaceDistance(source.triangles)
    # Match the engine baseline: source-cleanup losses are not cut damage.
    cleaned_source,_=clean_microscopic_components(manifold(model.source))
    before=SurfaceDistance(mesh(cleaned_source).triangles)
    regions=copy.deepcopy([r for r in model.regions if not r.get('hidden')])
    keep=[]
    for region in regions:
        if region.get('blocked'):continue
        if region['id']==result.parameters.region:
            region.update(blocked=True,accepted=True,reason='Already added as a part.');continue
        triangles=model.triangles[model.region_ids==region['id']]
        points=np.unique(np.vstack([triangles.reshape(-1,3),triangles.mean(1)]),axis=0)
        lost=distance(points)>.0001
        if lost.any():lost[np.flatnonzero(lost)[before(points[lost])>.0001]]=False
        if lost.any():
            region.update(blocked=True,reason='This painted area was changed by an earlier cut. Undo cuts to use it intact.')
        else:keep.append(region['id'])
    mask=np.isin(model.region_ids,keep)
    painted=model.triangles[mask];states=model.states[mask];ids=model.region_ids[mask]
    base_state=model.regions[0]['state'];context=len(regions)
    regions.append({'id':context,'state':base_state,'area':float(source.area),'triangles':len(source.faces),'bounds':source.bounds.tolist(),'hidden':True,'blocked':True})
    triangles=np.concatenate([painted,source.triangles])
    states=np.r_[states,np.full(len(source.faces),base_state,dtype=np.uint32)]
    ids=np.r_[ids,np.full(len(source.faces),context,dtype=np.int32)]
    history=copy.deepcopy(getattr(model,'socket_history',[]))
    new=before(source.triangles_center)>.0001
    if new.any():history.append({'name':'New part','triangles':source.triangles[new].copy()})
    updated=PaintedModel(model.name,source,triangles,states,ids,regions,model.palette,model.settings,model.warnings,copy.deepcopy(model.diagnostics),socket_history=history,display_triangles=len(painted))
    updated.diagnostics.pop('repair_approval',None)
    return updated


@dataclass
class AcceptedPart:
    id:str
    name:str
    region:int
    state:int
    solid:object
    result:object
    before_model:object


class Assembly:
    def __init__(self,model):
        self.original=model;self.model=model;self.parts=[];self.revision=0;self.body_name='Remaining body'
    def accept(self,result,name):
        name=part_name(name)
        if name.casefold() in [p.name.casefold() for p in self.parts]+[self.body_name.casefold()]:raise ValueError('Choose a unique part name.')
        region=result.parameters.region
        if self.model.regions[region].get('blocked'):raise ValueError('This region is no longer available.')
        for part in self.parts:
            if abs((result.extracted^part.solid).volume())>.001:raise ValueError(f'This cut overlaps "{part.name}". No part was added.')
        check_existing_sockets(self.model,result)
        updated=getattr(result,'next_model',None) or remaining_model(self.model,result)
        if len(updated.socket_history)>len(self.model.socket_history):updated.socket_history[-1]['name']=name
        record=AcceptedPart(uuid.uuid4().hex,name,region,self.model.regions[region]['state'],result.extracted,result,self.model)
        if len(updated.socket_history)>len(self.model.socket_history):updated.socket_history[-1]['part_id']=record.id
        self.parts.append(record);self.model=updated;self.revision+=1
        return record
    def undo(self):
        if not self.parts:raise ValueError('There are no accepted cuts to undo.')
        self.model=self.parts.pop().before_model
        names={p.id:p.name for p in self.parts}
        for socket in self.model.socket_history:
            if socket.get('part_id') in names:socket['name']=names[socket['part_id']]
        self.revision+=1
    def reset(self):
        self.parts=[];self.model=self.original;self.revision+=1
    def rename(self,id,name):
        name=part_name(name)
        existing=[p.name.casefold() for p in self.parts if p.id!=id]
        if id!='body':existing.append(self.body_name.casefold())
        if name.casefold() in existing:raise ValueError('Choose a unique part name.')
        if id=='body':self.body_name=name
        else:
            part=next((p for p in self.parts if p.id==id),None)
            if part is None:raise ValueError('This part no longer exists.')
            old=part.name;part.name=name
            for socket in self.model.socket_history:
                if socket['name']==old:socket['name']=name
        self.revision+=1
    def payload(self):
        payload=self.model.payload();payload['bounds']=self.original.source.bounds.tolist()
        payload['assembly']={'revision':self.revision,'body_name':self.body_name,'parts':[{'id':p.id,'name':p.name,'region':p.region,'state':p.state,'direction':DIRECTIONS[p.result.parameters.direction],'positions':packed(mesh(p.solid).triangles)} for p in self.parts]}
        return payload
    def export(self,selected):
        from .exporter import export_bundle
        if not isinstance(selected,list) or not selected or len(set(selected))!=len(selected):raise ValueError('Select one or more different parts to export.')
        allowed={p.id for p in self.parts}|{'body'}
        if not set(selected)<=allowed:raise ValueError('An export selection is no longer available.')
        if not self.parts:raise ValueError('Add a cut as a part before exporting the assembly.')
        solids=[(p.name,p.solid,p.state) for p in self.parts if p.id in selected]
        if 'body' in selected:solids.append((self.body_name,manifold(self.model.source),self.original.regions[0]['state']))
        cuts=[{'id':p.id,'name':p.name,'region':p.region,'parameters':asdict(p.result.parameters),'validation':p.result.report,'exported':p.id in selected} for p in self.parts]
        return export_bundle(self.original,self.parts[-1].result,named_solids=solids,report_override={'parameters':None,'validation':{'assembly_export':True,'cuts':cuts},'selected_part_ids':selected,'assembly_revision':self.revision,'remaining_body_exported':'body' in selected})
