"""Loopback-only local application. No cloud services or runtime CDN requests."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / '.runtime' / 'python'))
sys.path.insert(0, str(ROOT / 'src'))

import argparse
import datetime
import json
import mimetypes
import io
import zipfile
import threading
import traceback
import uuid
import numpy as np
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, unquote

from cutting_engine.model import load_3mf
from cutting_engine.engine import CutParameters, cut_region
from cutting_engine.exporter import export_bundle
from cutting_engine.repair import propose_repair
from cutting_engine.repair_export import export_repaired
from cutting_engine.jobs import CutJob

STATE = {'model': None, 'model_id': None, 'result': None, 'result_id': None, 'repair': None, 'repair_id': None, 'job': None}
LOCK = threading.Lock()
APP_ID = 'model-cleavage-local-v1'


class Handler(BaseHTTPRequestHandler):
    def respond(self, data, status=200, content_type='application/json'):
        if isinstance(data, dict):
            data = json.dumps(data).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        expected = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in expected:
            raise ValueError('Invalid local host.')
        origin = self.headers.get('Origin')
        if origin and urlparse(origin).netloc not in expected:
            raise ValueError('Only this local application may make requests.')

    def body(self, maximum=100 * 1024 * 1024):
        length = int(self.headers.get('Content-Length', 0))
        if length <= 0 or length > maximum:
            raise ValueError('Request is empty or too large.')
        return self.rfile.read(length)

    def do_GET(self):
        try:
            self.local_request()
            path = unquote(urlparse(self.path).path)
            if path == '/api/health':
                return self.respond({'app': APP_ID, 'ready': True})
            if path.startswith('/exports/'):
                target = (ROOT / 'output' / path.removeprefix('/exports/')).resolve()
                if not target.is_relative_to((ROOT / 'output').resolve()) or not target.is_file():
                    return self.respond({'error': 'Export not found.'}, 404)
                return self.respond(target.read_bytes(), content_type=mimetypes.guess_type(target)[0] or 'application/octet-stream')
            target = (ROOT / 'web' / (path.lstrip('/') or 'index.html')).resolve()
            if not target.is_relative_to((ROOT / 'web').resolve()) or not target.is_file():
                return self.respond({'error': 'Not found.'}, 404)
            self.respond(target.read_bytes(), content_type=mimetypes.guess_type(target)[0] or 'application/octet-stream')
        except (ValueError, OSError) as error:
            self.respond({'error': str(error)}, 400)

    def do_POST(self):
        try:
            self.local_request()
            action = urlparse(self.path).path
            if action not in ['/api/load', '/api/demo', '/api/region', '/api/preview', '/api/export', '/api/repair-preview', '/api/repair-approve', '/api/repair-cancel', '/api/repair-export', '/api/job-status', '/api/job-cancel', '/api/smooth-preview', '/api/smooth-apply', '/api/smooth-cancel', '/api/smooth-undo', '/api/parts/accept', '/api/parts/undo', '/api/parts/reset', '/api/parts/rename', '/api/parts/export']:
                return self.respond({'error': 'Unknown action.'}, 404)
            with LOCK:
                if action in ['/api/load', '/api/demo']:
                    if STATE['job'] is not None:
                        STATE['job'].cancel()
                        STATE['job'] = None
                    if action == '/api/demo':
                        demo = ROOT / 'examples' / 'BasicShapes001.3mf'
                        if not demo.exists():
                            raise ValueError('BasicShapes001.3mf was not found beside this project. Use Open 3MF instead.')
                        data, name = demo.read_bytes(), demo.name
                    else:
                        data = self.body()
                        name = Path(unquote(self.headers.get('X-File-Name', 'model.3mf'))).name
                    model = load_3mf(data, name)
                    STATE.update(smooth=None, undo=[], assembly=None)
                    STATE.update(model=model, model_id=uuid.uuid4().hex, result=None, result_id=None, repair=None, repair_id=None)
                    payload = model.payload()
                    payload['model_id'] = STATE['model_id']
                    return self.respond(payload)
                params = json.loads(self.body(65536))
                if STATE['model'] is None or params.get('model_id') != STATE['model_id']:
                    raise ValueError('The model changed. Load it again before continuing.')
                model = STATE['model']
                assembly=STATE.get('assembly')
                if action.startswith('/api/parts/'):
                    from cutting_engine.assembly import Assembly
                    if action=='/api/parts/accept':
                        if params.get('result_id')!=STATE['result_id'] or STATE['result'] is None:raise ValueError('Preview the current cut before adding it.')
                        assembly=assembly or Assembly(model)
                        assembly.accept(STATE['result'],params.get('name',''))
                        STATE['assembly']=assembly
                    else:
                        if assembly is None:raise ValueError('Add a part first.')
                        if params.get('revision')!=assembly.revision:raise ValueError('The parts changed. Refresh the parts list before continuing.')
                        if action=='/api/parts/export':
                            bundle=assembly.export(params.get('selected'))
                            stem=datetime.datetime.now().strftime('parts-%Y%m%d-%H%M%S-')+uuid.uuid4().hex[:6]
                            destination=ROOT/'output'/stem;destination.mkdir(parents=True)
                            filename='Model-Cleavage-parts.zip';(destination/filename).write_bytes(bundle)
                            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:warnings=json.loads(archive.read('cut-settings-and-validation.json')).get('export_warnings',[])
                            return self.respond({'url':f'/exports/{stem}/{filename}','folder':str(destination),'filename':filename,'warnings':warnings})
                        if action=='/api/parts/undo':assembly.undo()
                        elif action=='/api/parts/reset':assembly.reset()
                        elif action=='/api/parts/rename':assembly.rename(params.get('id'),params.get('name',''))
                    if STATE.get('job') is not None:STATE['job'].cancel()
                    STATE.update(model=assembly.model,model_id=uuid.uuid4().hex,result=None,result_id=None,job=None,smooth=None,repair=None,repair_id=None,undo=[])
                    payload=assembly.payload();payload['model_id']=STATE['model_id']
                    return self.respond(payload)
                if assembly is not None and assembly.parts and (action.startswith('/api/smooth-') or action.startswith('/api/repair-')):
                    raise ValueError('Reset accepted cuts before repairing or smoothing the source mesh.')
                if action.startswith('/api/smooth-'):
                    if STATE.get('job') is not None:
                        STATE['job'].cancel(); STATE['job']=None
                    if action == '/api/smooth-preview':
                        from cutting_engine.border_edit import smooth_border
                        from cutting_engine.interface import paint_boundary
                        from cutting_engine.model import packed
                        candidate, report = smooth_border(model,int(params['region']),float(params['amount']),float(params['band']))
                        token=uuid.uuid4().hex
                        STATE['smooth']=(token,candidate)
                        payload=candidate.payload(); payload.update(model_id=STATE['model_id'],smooth_id=token,smoothing_report=report)
                        for label,item in [('before',model),('after',candidate)]:
                            points,edges=paint_boundary(item.triangles[item.region_ids==int(params['region'])])
                            payload['border_'+label]=packed(points[edges])
                        return self.respond(payload)
                    if action == '/api/smooth-cancel':
                        STATE['smooth']=None
                        return self.respond({'cancelled':True})
                    if action == '/api/smooth-apply':
                        proposal=STATE.get('smooth')
                        if proposal is None or params.get('smooth_id')!=proposal[0]:raise ValueError('Preview smoothing again before applying.')
                        history=STATE.setdefault('undo',[]);history.append(model)
                        if len(history)>10:history.pop(0)
                        model=proposal[1]
                    else:
                        if not STATE.get('undo'):raise ValueError('There is no smoothing edit to undo.')
                        model=STATE['undo'].pop()
                    STATE.update(model=model,model_id=uuid.uuid4().hex,result=None,result_id=None,smooth=None,repair=None,repair_id=None,assembly=None)
                    payload=model.payload();payload.update(model_id=STATE['model_id'],can_undo=bool(STATE.get('undo')))
                    return self.respond(payload)
                if action in ['/api/job-status','/api/job-cancel']:
                    job=STATE['job']
                    if job is None or params.get('job_id') != job.id:
                        raise ValueError('This cut is no longer active.')
                    if action == '/api/job-cancel':
                        job.cancel()
                        STATE.update(result=None,result_id=None)
                        return self.respond({'state':'cancelled'})
                    status=job.status()
                    if status['state']=='done':
                        if STATE['result'] is None:
                            STATE.update(result=job.result(),result_id=uuid.uuid4().hex)
                        payload=STATE['result'].payload()
                        payload['result_id']=STATE['result_id']
                        status['result']=payload
                    return self.respond(status)
                if action == '/api/repair-preview':
                    proposal = propose_repair(model)
                    STATE.update(repair=proposal, repair_id=uuid.uuid4().hex)
                    payload = proposal.payload()
                    payload['repair_id'] = STATE['repair_id']
                    return self.respond(payload)
                if action == '/api/repair-cancel':
                    STATE.update(repair=None, repair_id=None)
                    return self.respond({'cancelled': True})
                if action == '/api/repair-approve':
                    if params.get('approved') is not True or params.get('repair_id') != STATE['repair_id'] or STATE['repair'] is None:
                        raise ValueError('Explicit approval of the current repair preview is required.')
                    repaired = STATE['repair'].candidate
                    repaired.diagnostics['repair_approval'] = {'approved': True, 'report': STATE['repair'].report}
                    STATE.update(model=repaired, model_id=uuid.uuid4().hex, result=None, result_id=None, repair=None, repair_id=None, smooth=None, undo=[], assembly=None)
                    payload = repaired.payload()
                    payload['model_id'] = STATE['model_id']
                    return self.respond(payload)
                if action == '/api/repair-export':
                    data = export_repaired(model)
                    stem = datetime.datetime.now().strftime('repair-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
                    destination = ROOT / 'output' / stem
                    destination.mkdir(parents=True)
                    filename = Path(model.name).stem + '-repaired.3mf'
                    (destination / filename).write_bytes(data)
                    return self.respond({'url': f'/exports/{stem}/{filename}', 'folder': str(destination), 'filename': filename})
                if action == '/api/region':
                    region = int(params['region'])
                    if 0<=region<len(model.regions) and model.regions[region].get('blocked'):raise ValueError(model.regions[region].get('reason','This region is not available.'))
                    if not 0 <= region < len(model.regions):
                        raise ValueError('Invalid region.')
                    if params.get('direction'):
                        return self.respond({'direction': params['direction'], 'plane': model.base_plane(params['direction'])})
                    if params.get('mode') == 'interface':
                        triangles=model.triangles[model.region_ids == region]
                        from cutting_engine.model import interface_direction
                        direction=interface_direction(triangles)
                        return self.respond({'direction':direction,'plane':0.0})
                    return self.respond(model.suggestion(region))
                if action == '/api/preview':
                    region=int(params['region'])
                    if not 0<=region<len(model.regions) or model.regions[region].get('blocked'):raise ValueError('This region is unavailable or was changed by an earlier cut. Undo cuts to use it intact.')
                    STATE.update(result=None, result_id=None)
                    cut = CutParameters(region=int(params['region']), direction=str(params['direction']),
                                        plane=float(params['plane']), depth=float(params['depth']),
                                        side_clearance=float(params.get('side_clearance', 0)),
                                        depth_clearance=float(params.get('depth_clearance', 0)),
                                        fastener=str(params.get('fastener', 'none')), mode=str(params.get('mode', 'planar')),
                                        root_taper_degrees=float(params.get('root_taper_degrees',0)), root_smoothing_mm=float(params.get('root_smoothing_mm',0)), minimum_fragment_width_mm=float(params.get('minimum_fragment_width_mm',.2)),
                                        fit_target=str(params.get('fit_target','body')),glue_width_mm=float(params.get('glue_width_mm',3)),glue_length_mm=float(params.get('glue_length_mm',1.5)),
                                        glue_depth_mm=float(params.get('glue_depth_mm',.5)),glue_taper_degrees=float(params.get('glue_taper_degrees',5)),glue_wall_mm=float(params.get('glue_wall_mm',.6)))
                    cut.validate()
                    if STATE['job'] is not None:
                        STATE['job'].cancel()
                    from dataclasses import asdict
                    job=CutJob(ROOT,model,STATE['model_id'],asdict(cut))
                    STATE['job']=job
                    return self.respond({'job_id':job.id,'state':'running'})
                if params.get('result_id') != STATE['result_id'] or STATE['result'] is None:
                    raise ValueError('Preview the current cut before exporting.')
                bundle = export_bundle(model, STATE['result'])
                stem = datetime.datetime.now().strftime('cut-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
                destination = ROOT / 'output' / stem
                destination.mkdir(parents=True)
                filename = 'Model-Cleavage-cut.zip'
                (destination / filename).write_bytes(bundle)
                with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                    export_warnings = json.loads(archive.read('cut-settings-and-validation.json')).get('export_warnings', [])
                return self.respond({'url': f'/exports/{stem}/{filename}', 'folder': str(destination), 'filename': filename, 'warnings': export_warnings})
        except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as error:
            self.respond({'error': str(error)}, 400)
        except Exception:
            traceback.print_exc()
            self.respond({'error': 'The geometry operation could not finish. Try a smaller region or another direction. Details were recorded in the local server log.'}, 500)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Model Cleavage ready at http://127.0.0.1:{args.port}', flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(f'http://127.0.0.1:{args.port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if STATE['job'] is not None:
            STATE['job'].cancel()
        server.server_close()
