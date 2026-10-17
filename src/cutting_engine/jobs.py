"""Single active cut process; caller holds the short application-state lock."""
import json,pickle,subprocess,sys,time,uuid
from pathlib import Path
import numpy as np
import manifold3d as mf
from .engine import CutParameters,CutResult


class CutJob:
    def __init__(self,root,model,model_id,params):
        self.id=uuid.uuid4().hex;self.model_id=model_id;self.started=time.monotonic();self.state='running'
        self.folder=Path(root)/'output'/'cut-jobs'/self.id
        self.folder.mkdir(parents=True)
        with (self.folder/'input.pkl').open('wb') as stream:pickle.dump((model,params),stream,pickle.HIGHEST_PROTOCOL)
        with (self.folder/'worker.log').open('wb') as log:
            self.process=subprocess.Popen([sys.executable,'-u',str(Path(root)/'cut_worker.py'),str(self.folder)],cwd=root,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

    def status(self):
        if self.state=='cancelled':return {'state':'cancelled','elapsed_seconds':time.monotonic()-self.started}
        for name in ['done.json','progress.json']:
            path=self.folder/name
            if path.exists():
                try:
                    data=json.loads(path.read_text(encoding='utf-8'))
                    if name=='done.json' or self.process.poll() is None:
                        if data['state']=='error':
                            (self.folder/'input.pkl').unlink(missing_ok=True)
                            if data.get('diagnostic_available'):
                                data['collision']=json.loads((self.folder/'collision-preview.json').read_text(encoding='utf-8'))
                        return data
                except (OSError,ValueError):pass
        if self.process.poll() is not None:return {'state':'error','error':'The cut worker stopped unexpectedly. See its local log.'}
        return {'state':'running','stage':'Starting cut','elapsed_seconds':time.monotonic()-self.started}

    def cancel(self):
        if self.process.poll() is None:
            self.process.kill();self.process.wait(timeout=5)
        self.state='cancelled'
        # Private model snapshot is no longer needed; preserve only timing/logs.
        (self.folder/'input.pkl').unlink(missing_ok=True)
        (self.folder/'result.pkl').unlink(missing_ok=True)

    def result(self):
        with (self.folder/'result.pkl').open('rb') as stream:data=pickle.load(stream)
        surfaces=[mf.Manifold(mf.Mesh64(np.array(v,dtype=np.float64,order='C',copy=True),np.array(f,dtype=np.uint64,order='C',copy=True))) for v,f in data['surfaces']]
        if any(solid.status()!=mf.Error.NoError for solid in surfaces):
            raise ValueError('The preview could not retain its validated solid topology. No export was created.')
        for solid,key in zip(surfaces[:2],['part_volume_mm3','base_volume_mm3']):
            expected=data['report'][key]
            if not np.isclose(solid.volume(),expected,rtol=1e-9,atol=.001):
                raise ValueError('The preview failed its full-precision volume transfer check. No export was created.')
        (self.folder/'input.pkl').unlink(missing_ok=True)
        (self.folder/'result.pkl').unlink(missing_ok=True)
        result=CutResult(CutParameters(**data['parameters']),*surfaces,data['report'])
        result.next_model=data.get('next_model')
        return result
