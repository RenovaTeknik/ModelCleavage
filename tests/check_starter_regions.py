"""Slow end-to-end starter audit; run separately from the unit suite."""
import sys,pathlib,time,json
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'.runtime/python'),str(ROOT/'src')]
from cutting_engine.model import load_3mf,interface_direction
from cutting_engine.engine import CutParameters,cut_region
from cutting_engine.exporter import export_bundle
model=load_3mf((ROOT/'tests/fixtures/BasicShapes001.3mf').read_bytes());rows=[]
folder=ROOT/'output'/'Starter Model Verified';folder.mkdir(parents=True,exist_ok=True)
for region in model.regions[1:11]:
 direction=interface_direction(model.triangles[model.region_ids==region['id']]);started=time.perf_counter()
 result=cut_region(model,CutParameters(region['id'],direction,0,2,side_clearance=.1,mode='interface',root_taper_degrees=3,root_smoothing_mm=.15))
 report=result.report
 assert report['part_pieces']==report['base_pieces']==1
 assert report['painted_surface_coverage']['missing_samples']==0
 assert report['part_volume_mm3']>region['area']*.5,'Starter feature unexpectedly became a thin skin'
 assert report['insertion_path']['max_overlap_mm3']<=.001
 row={'region':region['id'],'direction':direction,'seconds':time.perf_counter()-started,'volume_mm3':report['part_volume_mm3'],'part_pieces':report['part_pieces'],'base_pieces':report['base_pieces'],'coverage':report['painted_surface_coverage'],'withdrawal':report['insertion_path']['max_overlap_mm3']}
 rows.append(row);print(json.dumps(row),flush=True)
 if region['id'] in [1,2,5]:(folder/f'region-{region["id"]}-verified.zip').write_bytes(export_bundle(model,result))
(folder/'clearance-audit.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
print('PASS: all ten main starter regions with 0.1 mm side clearance, default taper/smoothing, painted coverage and withdrawal checks',flush=True)
