"""Runs one cut in a disposable process so cancellation also stops native work."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
import json,pickle,time,traceback
import numpy as np
from dataclasses import asdict
from cutting_engine.engine import CutParameters,cut_region
from cutting_engine.progress import _reporter


def run(folder):
    started=time.perf_counter();stage_started=started;current='Starting cut';timings={};last=0
    def update(stage,completed=None,total=None,force=False):
        nonlocal current,stage_started,last
        now=time.perf_counter()
        if stage != current:
            timings[current]=timings.get(current,0)+now-stage_started
            current=stage;stage_started=now;force=True
        if not force and now-last<.2:return
        last=now
        data={'state':'running','stage':current,'elapsed_seconds':now-started,'stage_elapsed_seconds':now-stage_started,'timings_seconds':timings,'completed':completed,'total':total}
        temporary=folder/'progress.tmp';temporary.write_text(json.dumps(data),encoding='utf-8')
        try:temporary.replace(folder/'progress.json')
        except PermissionError:pass
    token=_reporter.set(update)
    try:
        update('Starting cut',force=True)
        with (folder/'input.pkl').open('rb') as stream:model,params=pickle.load(stream)
        result=cut_region(model,CutParameters(**params))
        update('Preparing preview',force=True)
        def surface(solid):
            value=solid.to_mesh64()
            return np.asarray(value.vert_properties)[:,:3],np.asarray(value.tri_verts)
        data={'parameters':asdict(result.parameters),'report':result.report,'surfaces':[surface(s) for s in [result.extracted,result.remainder,result.nominal_remainder]]}
        with (folder/'result.tmp').open('wb') as stream:pickle.dump(data,stream,pickle.HIGHEST_PROTOCOL)
        (folder/'result.tmp').replace(folder/'result.pkl')
        now=time.perf_counter();timings[current]=timings.get(current,0)+now-stage_started
        data['report']['performance']={'total_seconds':now-started,'stages_seconds':timings}
        # Report includes timings in both preview and later exported validation.
        with (folder/'result.pkl').open('wb') as stream:pickle.dump(data,stream,pickle.HIGHEST_PROTOCOL)
        (folder/'done.json').write_text(json.dumps({'state':'done','elapsed_seconds':now-started,'timings_seconds':timings}),encoding='utf-8')
    except Exception as error:
        timings[current]=timings.get(current,0)+time.perf_counter()-stage_started
        traceback.print_exc()
        message=str(error) if isinstance(error,ValueError) else 'The cut could not finish. Details are in the local cut log.'
        diagnostic_available=hasattr(error,'diagnostic_payload')
        if diagnostic_available:
            diagnostic=error.diagnostic_payload()
            (folder/'collision-report.json').write_text(json.dumps(diagnostic['report'],indent=2),encoding='utf-8')
            (folder/'collision-preview.json').write_text(json.dumps(diagnostic),encoding='utf-8')
        (folder/'done.json').write_text(json.dumps({'state':'error','error':message,'stage':current,'elapsed_seconds':time.perf_counter()-started,'timings_seconds':timings,'diagnostic_available':diagnostic_available}),encoding='utf-8')
    finally:_reporter.reset(token)

if __name__=='__main__':run(Path(sys.argv[1]))
