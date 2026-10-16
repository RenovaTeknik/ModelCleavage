import * as THREE from 'three';
import { OrbitControls } from '/vendor/OrbitControls.js';

const $ = id => document.getElementById(id);
const app = { model: null, selected: null, result: null, mode: 'original', busy: false, selectionVersion: 0 };
const scene = new THREE.Scene();
const renderer = new THREE.WebGLRenderer({ canvas: $('canvas'), antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
const camera = new THREE.PerspectiveCamera(37, 1, .1, 10000);
camera.up.set(0, 0, 1);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
const root = new THREE.Group(); scene.add(root);
scene.add(new THREE.HemisphereLight(0xe5f0e6, 0x44505b, 2.1));
const key = new THREE.DirectionalLight(0xffffff, 2.2); key.position.set(-100, -170, 260); scene.add(key);
const fill = new THREE.DirectionalLight(0xb6d4df, .8); fill.position.set(180, 100, 70); scene.add(fill);
let originalMesh, highlight, baseMesh, partMesh, grid, arrow, collisionMesh, collisionBox;
let problemMesh, repairMesh, removedMesh, repairProposal;

function clearRepairView() {
  for (const object of [problemMesh, repairMesh, removedMesh]) dispose(object);
  problemMesh = repairMesh = removedMesh = null; repairProposal = null;
  $('repair-review').hidden = true; $('repair-consent').checked = false; $('repair-approve').disabled = true;
}
function showRepairProposal(show) {
  if (!repairProposal) return;
  originalMesh.visible = !show;
  if (highlight) highlight.visible = false;
  if (problemMesh) problemMesh.visible = !show && $('show-problems').checked;
  repairMesh.visible = show; removedMesh.visible = show;
  $('view-title').textContent = show ? 'Proposed repair · red surfaces removed' : 'Original · red problem areas';
}
const raycaster = new THREE.Raycaster();
let pointerDown;

function dispose(object) {
  if (!object) return;
  root.remove(object); scene.remove(object);
  object.geometry?.dispose();
  if (Array.isArray(object.material)) object.material.forEach(m => m.dispose());
  else object.material?.dispose();
}
function typed(encoded, Type = Float32Array) {
  const string = atob(encoded), bytes = new Uint8Array(string.length);
  for (let i = 0; i < string.length; i++) bytes[i] = string.charCodeAt(i);
  return new Type(bytes.buffer);
}
function geometry(positions) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  g.computeVertexNormals(); g.computeBoundingSphere();
  return g;
}
function plainMesh(positions, colour) {
  return new THREE.Mesh(geometry(positions), new THREE.MeshStandardMaterial({ color: colour, roughness: .78, metalness: .03 }));
}
function notice(message, error = false) {
  $('feedback').hidden = !message;
  $('feedback').classList.toggle('error', error);
  $('feedback').textContent = message || '';
}
function updateFooterStatus() {
  if (!$('export').disabled && app.result) {
    $('bottom-status').textContent = 'Preview ready · move Separate preview to inspect the solid part and recess';
  } else if (app.collision) {
    $('bottom-status').textContent = 'Collision inspection only · red shows intersection · no printable export';
  } else if (app.model) {
    const size = app.model.bounds[1].map((value, i) => (value - app.model.bounds[0][i]).toFixed(1));
    $('bottom-status').textContent = `${app.model.name} · ${size.join(' × ')} mm`;
  } else {
    $('bottom-status').textContent = 'Ready to open a model';
  }
}
function busy(active, text = 'Working…') {
  $('border-settings').disabled=active || app.selected===null || !app.model?.cut_ready || !!app.borderProposal;
  $('border-undo').disabled=active || !app.model?.can_undo || !!app.borderProposal;
  app.busy = active; $('busy').hidden = !active; $('busy-text').textContent = text;
  $('open-file').disabled = active; $('demo').disabled = active; $('empty-demo').disabled = active;
  $('settings').disabled = active || app.selected === null || !app.model?.cut_ready || !!app.borderProposal;
  $('export').disabled = active || !app.result;
  updateFooterStatus();
  $('save-repaired').disabled = active;
  document.querySelectorAll('.region').forEach(b => b.disabled = active);
  $('repair-preview').disabled = active;
  $('repair-approve').disabled = active || !$('repair-consent').checked || !repairProposal;
}
async function request(path, payload, extra = {}) {
  const response = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...extra.headers },
    body: payload instanceof File ? payload : JSON.stringify(payload),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The operation could not finish.');
  return result;
}
function clearPreview() {
  dispose(collisionMesh); dispose(collisionBox); collisionMesh=collisionBox=null; app.collision=null;
  $('collision-diagnostics').hidden=true; $('cut-view').textContent='Cut preview';
  dispose(baseMesh); dispose(partMesh); baseMesh = partMesh = null;
  app.result = null; $('cut-view').disabled = true; $('export').disabled = true;
  $('validation').hidden = true; $('validation').open = false; updateFooterStatus(); $('explode').disabled = true; $('explode').value = '0'; $('explode-value').textContent = '0 mm';
  setMode('original');
}
function invalidate() {
  clearPreview(); notice('Settings changed. Preview the cut to check the new geometry.'); updateArrow();
}
function setMode(mode) {
  if (mode === 'cut' && app.collision) mode='collision';
  if (mode === 'cut' && !app.result) return;
  if (mode === 'original' && repairProposal) showRepairProposal(false);
  app.mode = mode;
  if (originalMesh) originalMesh.visible = mode === 'original';
  if (highlight) highlight.visible = mode === 'original';
  if (baseMesh) baseMesh.visible = mode !== 'original';
  if (collisionMesh) collisionMesh.visible=mode==='collision';
  if (collisionBox) collisionBox.visible=mode==='collision';
  if (partMesh) partMesh.visible = mode !== 'original';
  if (arrow) arrow.visible = mode === 'original';
  $('original-view').classList.toggle('active', mode === 'original'); $('cut-view').classList.toggle('active', mode !== 'original');
  $('view-title').textContent = mode === 'cut' ? 'Solid part + matching pocket' : 'Painted surface';
  if (mode==='collision') $('view-title').textContent=`Collision at ${app.collision.at_offset_mm.toFixed(3)} mm travel · red is overlap`;
  $('explode').disabled = mode !== 'cut';
}
function resetCamera() {
  if (!app.model) { camera.position.set(150, -100, 140); controls.target.set(0, 0, 0); }
  else {
    const size = new THREE.Vector3().fromArray(app.model.bounds[1]).sub(new THREE.Vector3().fromArray(app.model.bounds[0]));
    const distance = Math.max(size.x, size.y, size.z) * 2.25;
    camera.position.set(distance * .86, -distance * .49, distance * .76); controls.target.set(0, 0, 0);
    camera.near = Math.max(.01, distance / 10000); camera.far = distance * 100; camera.updateProjectionMatrix();
  }
  controls.update();
}
function resize() {
  const rect = $('viewport').getBoundingClientRect();
  renderer.setSize(rect.width, rect.height, false); camera.aspect = rect.width / rect.height; camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe($('viewport'));
function frame() { requestAnimationFrame(frame); controls.update(); renderer.render(scene, camera); }
resetCamera(); resize(); frame();

function regionLabel(region) { return `Filament ${region.state} · area ${region.id + 1}`; }
function showRegions() {
  $('regions').replaceChildren();
  for (const region of app.model.regions) {
    const button = document.createElement('button'); button.className = 'region'; button.dataset.region = region.id;
    const swatch = document.createElement('span'); swatch.className = 'swatch'; swatch.style.background = app.model.palette[region.state - 1];
    const text = document.createElement('span'); const label = document.createElement('span'); label.textContent = regionLabel(region);
    const area = document.createElement('small'); area.textContent = `${region.area.toLocaleString(undefined, { maximumFractionDigits: 1 })} mm²`;
    text.append(label, area); const next = document.createElement('span'); next.className = 'arrow'; next.textContent = '↗';
    button.append(swatch, text, next); button.addEventListener('click', () => selectRegion(region.id)); $('regions').append(button);
  }
  const grouped = app.model.regions.reduce((sum, r) => sum + (r.grouped_islands || 0), 0);
  $('region-count').textContent = app.model.regions.length;
  $('model-stats').title = grouped ? `${grouped} tiny islands grouped with nearby larger regions of the same colour (up to 0.5 mm², within 0.5 mm). Paint is unchanged.` : '';
  if (grouped) $('model-stats').textContent += ` · ${grouped} tiny islands grouped`;
}
function mountModel(model) {
  dispose(borderLines); borderLines=null; app.borderProposal=null; $('border-review').hidden=true; $('border-settings').disabled=true; $('border-preview').disabled=false; $('border-amount').disabled=$('border-band').disabled=false;
  clearRepairView();
  for (const object of [originalMesh, highlight, baseMesh, partMesh, arrow, grid]) dispose(object);
  originalMesh = highlight = baseMesh = partMesh = arrow = grid = null;
  app.model = model; app.selected = null; app.result = null;
  model.positions = typed(model.positions); model.states = typed(model.states, Uint32Array); model.region_ids = typed(model.region_ids, Uint32Array);
  const g = geometry(model.positions), colours = new Float32Array(model.positions.length);
  const palette = model.palette.map(c => new THREE.Color(c));
  for (let i = 0; i < model.states.length; i++) {
    const c = palette[model.states[i] - 1];
    for (let vertex = 0; vertex < 3; vertex++) colours.set([c.r, c.g, c.b], i * 9 + vertex * 3);
  }
  g.setAttribute('color', new THREE.BufferAttribute(colours, 3));
  originalMesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: .83, metalness: .02 })); root.add(originalMesh);
  const low = new THREE.Vector3().fromArray(model.bounds[0]), high = new THREE.Vector3().fromArray(model.bounds[1]);
  const centre = low.clone().add(high).multiplyScalar(.5); root.position.copy(centre).negate();
  const span = Math.max(...high.clone().sub(low).toArray());
  grid = new THREE.GridHelper(Math.ceil(span * 1.6 / 10) * 10, 20, 0x4d5e58, 0x35413e);
  grid.rotation.x = Math.PI / 2; grid.position.z = low.z - centre.z - .2; grid.material.transparent = true; grid.material.opacity = .4; scene.add(grid);
  $('empty-view').hidden = true; $('model-name').textContent = model.name;
  $('model-stats').textContent = `${model.original_triangles.toLocaleString()} mesh triangles · ${model.paint_triangles.toLocaleString()} painted facets`;
  $('selection-name').textContent = 'Select a painted area'; $('selection-area').textContent = 'Click a surface or choose from the list';
  $('selection').querySelector('.selection-dot').style.background = '#55625f';
  $('diagnostics').hidden = model.cut_ready;
  $('save-repaired').hidden = !model.diagnostics?.repair_approval?.approved;
  if (!model.cut_ready) {
    const d = model.diagnostics;
    $('diagnostic-summary').textContent = `${d.nonmanifold_edges} non-manifold edges · ${d.open_edges} open edges · ${d.problem_faces} affected faces. Red overlays can be hidden to inspect the paint underneath.`;
    problemMesh = new THREE.Mesh(geometry(typed(model.problem_positions)), new THREE.MeshBasicMaterial({ color: 0xff503e, transparent: true, opacity: .75, side: THREE.DoubleSide, depthTest: false, depthWrite: false }));
    problemMesh.renderOrder = 5; root.add(problemMesh); $('show-problems').checked = true;
  }
  showRegions(); clearPreview(); resetCamera();
  $('bottom-status').textContent = `${model.name} · ${high.clone().sub(low).toArray().map(n => n.toFixed(1)).join(' × ')} mm`;
  notice(model.cut_ready ? 'Model ready. Select one painted region. Nearby tiny areas of the same colour are grouped automatically.' : 'Inspection mode: red areas need review. Preview a repair to see its changes before deciding whether to approve.');
}
async function load(file = null) {
  if (app.busy) return;
  busy(true, 'Decoding painted regions…'); notice('');
  try {
    const payload = file ? await request('/api/load', file, { headers: { 'Content-Type': 'application/octet-stream', 'X-File-Name': encodeURIComponent(file.name) } }) : await request('/api/demo', {});
    mountModel(payload);
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
}
function updateArrow() {
  dispose(arrow); arrow = null;
  if (app.selected === null || !app.model) return;
  const directions = { '+X': [1, 0, 0], '-X': [-1, 0, 0], '+Y': [0, 1, 0], '-Y': [0, -1, 0], '+Z': [0, 0, 1], '-Z': [0, 0, -1] };
  const n = new THREE.Vector3().fromArray(directions[$('direction').value]);
  const bounds = app.model.regions[app.selected].bounds;
  const point = new THREE.Vector3().fromArray(bounds[0]).add(new THREE.Vector3().fromArray(bounds[1])).multiplyScalar(.5);
  if ($('cut-method').value === 'planar') point.addScaledVector(n, Number($('plane').value) - point.dot(n));
  arrow = new THREE.ArrowHelper(n, point, 22, 0xb8ed92, 4, 2); root.add(arrow); arrow.visible = app.mode === 'original';
}
async function selectRegion(id) {
  if (app.busy || !app.model) return;
  const version = ++app.selectionVersion;
  if (app.borderProposal) { notice('Apply or cancel the smoothing preview before selecting another area.'); return; }
  app.selected = id; $('border-settings').disabled=!app.model.cut_ready; clearPreview(); dispose(highlight);
  const model = app.model, region = model.regions[id];
  const selected = new Float32Array(region.triangles * 9); let next = 0;
  for (let i = 0; i < model.region_ids.length; i++) if (model.region_ids[i] === id) { selected.set(model.positions.subarray(i * 9, i * 9 + 9), next); next += 9; }
  highlight = new THREE.Mesh(geometry(selected), new THREE.MeshBasicMaterial({ color: 0xc7f2a7, transparent: true, opacity: .4, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2 }));
  highlight.renderOrder = 2; root.add(highlight);
  document.querySelectorAll('.region').forEach(button => button.classList.toggle('active', Number(button.dataset.region) === id));
  $('selection-name').textContent = regionLabel(region); $('selection-area').textContent = `${region.area.toFixed(1)} mm² of painted surface`;
  $('selection').querySelector('.selection-dot').style.background = model.palette[region.state - 1]; $('settings').disabled = true;
  notice('Finding a suggested direction and base plane…');
  try {
    const suggestion = await request('/api/region', { model_id: model.model_id, region: id, mode: $('cut-method').value });
    if (version !== app.selectionVersion || app.model !== model) return;
    $('direction').value = suggestion.direction; $('plane').value = suggestion.plane ?? 0;
    notice('Region selected. Check the pull direction and base plane, then preview the cut.'); updateArrow();
  } catch (error) { if (version === app.selectionVersion) notice(error.message, true); }
  finally { if (version === app.selectionVersion) $('settings').disabled = !app.model.cut_ready; }
}
async function autoPlane() {
  if (!app.model || app.selected === null) return;
  const version = app.selectionVersion, direction = $('direction').value;
  // Returning the selected axis's dominant base plane avoids changing the chosen direction.
  const result = await request('/api/region', { model_id: app.model.model_id, region: app.selected, direction: $('direction').value });
  if (version !== app.selectionVersion || direction !== $('direction').value) return;
  $('plane').value = result.plane ?? 0; invalidate();
}
async function preview() {
  if (app.selected === null || app.busy || !app.model.cut_ready) return;
  busy(true, 'Building solid part and pocket…'); clearPreview(); notice('');
  try {
    const job = await request('/api/preview', { model_id: app.model.model_id, region: app.selected, direction: $('direction').value, plane: Number($('plane').value), depth: Number($('depth').value), side_clearance: Number($('side-clearance').value), depth_clearance: Number($('depth-clearance').value), fastener: $('fastener').value, fit_target: $('fit-target').value, glue_width_mm: Number($('glue-width').value), glue_length_mm: Number($('glue-length').value), glue_depth_mm: Number($('glue-depth').value), glue_taper_degrees: Number($('glue-taper').value), glue_wall_mm: Number($('glue-wall').value), minimum_fragment_width_mm: Number($('fragment-width').value), mode: $('cut-method').value, root_taper_degrees: $('cut-method').value==='interface' ? Number($('root-taper').value) : 0, root_smoothing_mm: $('cut-method').value==='interface' ? Number($('root-smoothing').value) : 0 });
    const session = {id:job.job_id,model_id:app.model.model_id,cancelRequested:false,cancelPromise:null};
    app.cutSession=session;
    $('cancel-cut').hidden=false; $('cancel-cut').disabled=false; $('cancel-cut').textContent='Cancel cut';
    const started=performance.now();
    let result;
    while (!result) {
      if (session.cancelRequested) { await session.cancelPromise; throw new Error('Cut cancelled. Your loaded model and repair are unchanged.'); }
      const status=await request('/api/job-status',{model_id:session.model_id,job_id:session.id});
      if (session.cancelRequested) { await session.cancelPromise; throw new Error('Cut cancelled. Your loaded model and repair are unchanged.'); }
      if (status.state==='error') { if (status.collision) showCollision(status.collision); throw new Error(status.error); }
      if (status.state==='cancelled') throw new Error('Cut cancelled. Your loaded model and repair are unchanged.');
      if (status.state==='done') { result=status.result;break; }
      $('busy-text').textContent=status.stage || 'Working on cut';
      const seconds=Math.floor((performance.now()-started)/1000);
      const stageProgress=status.total>0 && status.completed!==null ? ` · ${Math.min(100,Math.round(status.completed/status.total*100))}% of this stage` : '';
      $('cut-elapsed').textContent=`${seconds}s elapsed${stageProgress}`;
      await new Promise(resolve=>setTimeout(resolve,400));
    }
    app.result = result;
    const selected = app.model.regions[app.selected];
    partMesh = plainMesh(typed(result.part), app.model.palette[selected.state - 1]);
    const dominant = app.model.regions[0].state; baseMesh = plainMesh(typed(result.remainder), app.model.palette[dominant - 1]);
    root.add(baseMesh, partMesh); $('cut-view').disabled = false; setMode('cut');
    const report = result.report;
    const fitLines=report.fit_allowances ? [`Effective fit · ${report.fit_allowances.effective_side_mm} mm per side · ${report.fit_allowances.effective_depth_mm} mm extra depth · ${({body:'main body',part:'excised part',both:'half on each'})[report.fit_allowances.target]}`] : [];
    const timingLines=report.performance ? [`Cut completed in ${report.performance.total_seconds.toFixed(1)} s`] : [];
    const interfaceLines = report.cut_mode === 'interface' ? [...(report.painted_surface_coverage?.checked ? [report.painted_surface_coverage.excluded_fit_seam_samples ? `✓ Painted interior retained · ${report.painted_surface_coverage.excluded_fit_seam_samples} seam-allowance samples trimmed` : report.painted_surface_coverage.excluded_numerical_relief_samples ? `✓ Painted core retained · ${report.painted_surface_coverage.excluded_numerical_relief_samples} numerical-skin samples relieved` : '✓ Whole painted feature retained'] : []),`Interface profile · flat cap at ${report.interface.cap_plane.toFixed(2)} mm on pull axis`, `Seam outline deviation ${report.interface.interface_outline_deviation_mm.toFixed(3)} mm · insertion path checked`, `Plug taper ${report.interface.root_taper_degrees || 0}° · smoothing ${report.interface.root_smoothing_mm || 0} mm${report.interface.root_tip?.seam_anchored ? ' · starts at paint seam' : ''}`, ...(report.interface.shared_bottom_preserved ? ['Shared flat bottom preserved'] : [])] : [];
    const corrections = Object.values(report.automatic_cleanup || {}).flat();
    const thinCount=(report.thin_fragment_filter?.nominal || []).length;
    const thinLines=thinCount ? [`✓ ${thinCount} thin cut fragment(s) joined to part · ${report.thin_fragment_filter.minimum_width_mm} mm width limit`] : [];
    const cleanupLines = corrections.length ? [`${corrections.length} microscopic defects corrected automatically`, `${(report.source_cleanup_absolute_mm3 || 0).toFixed(6)} mm³ source cleanup; original file unchanged`] : [];
    $('checks').replaceChildren();
    for (const line of ['✓ Closed solids', '✓ Nominal shape checked before fit and relief', '✓ No significant overlap', ...interfaceLines, ...fitLines, ...timingLines, ...cleanupLines, ...thinLines, ...(report.glue_keys?.enabled ? ['✓ Paired undercut glue pockets · surrounding material checked'] : []), `${report.part_pieces} removable piece(s) · ${report.base_pieces} base piece(s)`, `${report.part_volume_mm3.toFixed(1)} mm³ removable volume`, ...(report.fit_gap_volume_mm3 > .001 ? [`${report.fit_gap_volume_mm3.toFixed(2)} mm³ intentional fit gap`] : [])]) {
      const row = document.createElement('div'); row.textContent = line; $('checks').append(row);
    }
    $('validation').hidden = false;
    notice(report.warnings.join(' '));
    updateFooterStatus();
  } catch (error) { notice(error.message, !app.cutSession?.cancelRequested); }
  finally { app.cutSession=null; $('cancel-cut').hidden=true; $('cut-elapsed').textContent='Working locally'; busy(false); }
}

$('open-file').onclick = () => $('file').click();
$('file').onchange = event => { if (event.target.files[0]) load(event.target.files[0]); event.target.value = ''; };
$('demo').onclick = $('empty-demo').onclick = () => load();
$('reset-view').onclick = resetCamera;
$('original-view').onclick = () => setMode('original'); $('cut-view').onclick = () => setMode('cut');
$('preview').onclick = preview;
$('auto-plane').onclick = () => autoPlane().catch(error => notice(error.message, true));
$('direction').onchange = () => { invalidate(); if ($('cut-method').value === 'planar') autoPlane().catch(error => notice(error.message, true)); };
$('depth-range').oninput = () => { $('depth').value = $('depth-range').value; invalidate(); };
$('depth').oninput = () => { $('depth-range').value = $('depth').value; invalidate(); };
$('plane').oninput = invalidate;
for (const id of ['side-clearance', 'depth-clearance']) $(id).oninput = () => {
  $('fit-summary').textContent = Number($('side-clearance').value) || Number($('depth-clearance').value) ? 'Custom gap · ≥0.05 mm' : '0.05 mm minimum'; invalidate();
};
$('explode').oninput = () => {
  const value = Number($('explode').value); $('explode-value').textContent = `${value} mm`;
  if (partMesh && app.result) partMesh.position.fromArray(app.result.direction).multiplyScalar(value);
};
$('export').onclick = async () => {
  if (!app.result || app.busy) return;
  busy(true, 'Saving printable parts…');
  try {
    const saved = await request('/api/export', { model_id: app.model.model_id, result_id: app.result.result_id });
    const a = document.createElement('a'); a.href = saved.url; a.download = saved.filename; a.click();
    notice(`Saved to ${saved.folder}. A download of the same ZIP has also started. ${(saved.warnings || []).join(' ')}`);
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
};
$('canvas').addEventListener('pointerdown', event => { pointerDown = [event.clientX, event.clientY]; });
$('canvas').addEventListener('pointerup', event => {
  if (app.mode !== 'original' || !originalMesh || app.busy || !pointerDown) return;
  if (Math.hypot(event.clientX - pointerDown[0], event.clientY - pointerDown[1]) > 5) return;
  const rect = $('canvas').getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1), camera);
  const hit = raycaster.intersectObject(originalMesh, false)[0];
  if (hit) selectRegion(app.model.region_ids[hit.faceIndex]);
});
window.addEventListener('error', event => notice(`Interface error: ${event.message}`, true));

$('show-problems').onchange = () => { if (problemMesh) problemMesh.visible = $('show-problems').checked && !repairMesh?.visible; };
$('repair-original').onclick = () => showRepairProposal(false);
$('repair-proposed').onclick = () => showRepairProposal(true);
$('repair-consent').onchange = () => { $('repair-approve').disabled = !$('repair-consent').checked || app.busy || !repairProposal; };
$('repair-preview').onclick = async () => {
  if (app.busy || !app.model || app.model.cut_ready) return;
  busy(true, 'Inspecting proposed geometry repair…');
  try {
    const proposal = await request('/api/repair-preview', { model_id: app.model.model_id });
    dispose(repairMesh); dispose(removedMesh); repairProposal = proposal;
    repairMesh = plainMesh(typed(proposal.positions), '#bdc9c7');
    removedMesh = new THREE.Mesh(geometry(typed(proposal.changed_positions)), new THREE.MeshBasicMaterial({ color: 0xff503e, transparent: true, opacity: .8, side: THREE.DoubleSide, depthTest: false, depthWrite: false }));
    removedMesh.renderOrder = 6; root.add(repairMesh, removedMesh);
    const r = proposal.report;
    $('repair-summary').textContent = `${r.before_triangles.toLocaleString()} → ${r.after_triangles.toLocaleString()} triangles. ${r.removed_triangles.toLocaleString()} original faces removed; ${r.new_surfaces.toLocaleString()} changed faces. Volume change: ${(r.after_volume_mm3-r.before_volume_mm3).toFixed(6)} mm³. Surface area change: ${r.surface_area_change_mm2.toFixed(3)} mm². Colour on ${r.approximated_colour_faces.toLocaleString()} changed faces is approximated from the nearest original paint; fine boundaries there may change. Retained faces keep their paint.`;
    $('repair-review').hidden = false; $('repair-consent').checked = false;
    showRepairProposal(true); notice('This is a proposal only. Compare the views, then approve or cancel.');
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
};
$('repair-cancel').onclick = async () => {
  try { await request('/api/repair-cancel', { model_id: app.model.model_id }); }
  catch (error) { notice(error.message, true); return; }
  dispose(repairMesh); dispose(removedMesh); repairMesh = removedMesh = null; repairProposal = null;
  $('repair-review').hidden = true; $('repair-consent').checked = false; originalMesh.visible = true;
  if (problemMesh) problemMesh.visible = $('show-problems').checked;
  notice('Repair cancelled. The original model is unchanged and remains in inspection mode.');
};
$('repair-approve').onclick = async () => {
  if (!repairProposal || !$('repair-consent').checked || app.busy) return;
  busy(true, 'Applying approved repair to the working copy…');
  try {
    const model = await request('/api/repair-approve', { model_id: app.model.model_id, repair_id: repairProposal.repair_id, approved: true });
    mountModel(model); notice('Approved repair applied to the working copy. The source file is unchanged. Save the repaired 3MF, or select a region to cut.');
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
};

function updateCutMethod() {
  const active = $('cut-method').value === 'interface';
  $('plane-controls').hidden = active;
  $('plug-controls').hidden = !active;
  $('fragment-controls').hidden = !active;
  $('side-clearance').disabled = false;
  $('method-hint').textContent = active ? 'Keeps the whole painted feature, including returning curves, and adds a straight root with a flat cap. Full painted-surface coverage and the insertion path are checked.' : 'Projects the selected footprint from the chosen base plane. Suitable for planar features.';
  $('fit-summary').textContent = Number($('side-clearance').value) || Number($('depth-clearance').value) ? 'Custom gap · ≥0.05 mm' : '0.05 mm minimum';
}
$('cut-method').onchange = () => { updateCutMethod(); if (app.selected !== null) selectRegion(app.selected); else invalidate(); };
updateCutMethod();

$('save-repaired').onclick = async () => {
  if (app.busy || !app.model?.diagnostics?.repair_approval?.approved) return;
  busy(true, 'Saving repaired 3MF...');
  try {
    const saved = await request('/api/repair-export', { model_id: app.model.model_id });
    const a = document.createElement('a'); a.href = saved.url; a.download = saved.filename; a.click();
    notice(`Repaired 3MF saved to ${saved.folder}. Original paint is retained on unchanged faces; changed faces use the approved colour approximations.`);
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
};

$('cancel-cut').onclick = () => {
  const session=app.cutSession;
  if (!session || session.cancelRequested) return;
  session.cancelRequested=true;
  $('cancel-cut').disabled=true; $('cancel-cut').textContent='Cancelling...';
  session.cancelPromise=request('/api/job-cancel',{model_id:session.model_id,job_id:session.id});
  session.cancelPromise.catch(()=>{});
};

function showCollision(data) {
  app.collision=data.report;
  const state=app.model.regions[app.selected].state;
  baseMesh=plainMesh(typed(data.base),app.model.palette[app.model.regions[0].state-1]);
  partMesh=plainMesh(typed(data.part),app.model.palette[state-1]);
  collisionMesh=new THREE.Mesh(geometry(typed(data.overlap)),new THREE.MeshBasicMaterial({color:0xff3028,side:THREE.DoubleSide,depthTest:false,depthWrite:false,transparent:true,opacity:.95}));
  collisionMesh.renderOrder=8;
  const r=data.report;
  const bounds=new THREE.Box3(new THREE.Vector3().fromArray(r.bounds[0]),new THREE.Vector3().fromArray(r.bounds[1]));
  collisionBox=new THREE.Box3Helper(bounds,0xff6453);collisionBox.material.depthTest=false;collisionBox.renderOrder=9;
  root.add(baseMesh,partMesh,collisionMesh,collisionBox);
  $('collision-summary').textContent=`Maximum overlap: ${r.max_overlap_mm3.toPrecision(5)} mm³ at ${r.at_offset_mm.toFixed(3)} mm travel. Allowed numerical overlap: ${r.tolerance_mm3} mm³. ${r.component_count} contact component(s). Red surfaces show the measured intersection; the part is shown at that travel position. Export is blocked.`;
  $('collision-samples').replaceChildren();
  for (const sample of r.samples) {
    const row=document.createElement('div');row.textContent=`${sample.offset_mm.toFixed(3)} mm travel: ${sample.overlap_mm3.toPrecision(5)} mm³`; $('collision-samples').append(row);
  }
  $('collision-diagnostics').hidden=false;$('cut-view').textContent='Collision view';$('cut-view').disabled=false;
  $('export').disabled=true;setMode('collision');
  $('bottom-status').textContent='Collision inspection only · red shows intersection · no printable export';
}
$('focus-collision').onclick=()=>{
  if (!app.collision) return;
  setMode('collision');
  const bounds=app.collision.components[0]?.bounds || app.collision.bounds;
  const box=new THREE.Box3(new THREE.Vector3().fromArray(bounds[0]),new THREE.Vector3().fromArray(bounds[1]));
  const target=root.localToWorld(box.getCenter(new THREE.Vector3()));
  const span=Math.max(2,box.getSize(new THREE.Vector3()).length());
  const direction=camera.position.clone().sub(controls.target).normalize();
  camera.position.copy(target).addScaledVector(direction,span*2.5);controls.target.copy(target);controls.update();
};

$('root-taper-range').oninput=()=>{$('root-taper').value=$('root-taper-range').value;invalidate();};
$('root-taper').oninput=()=>{$('root-taper-range').value=$('root-taper').value;invalidate();};
$('root-smoothing').oninput=invalidate;

let borderLines;
function drawBorderSegments(encoded,colour) {
  dispose(borderLines); borderLines=null;
  if (!encoded)return;
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.BufferAttribute(typed(encoded),3));
  borderLines=new THREE.LineSegments(g,new THREE.LineBasicMaterial({color:colour,depthTest:false}));borderLines.renderOrder=10;root.add(borderLines);
}
function borderView(after) {
  const proposal=app.borderProposal;if(!proposal)return;
  const positions=after ? typed(proposal.positions) : app.model.positions;
  originalMesh.geometry.dispose();originalMesh.geometry=geometry(positions);
  const colours=new Float32Array(positions.length),palette=app.model.palette.map(c=>new THREE.Color(c));
  for(let i=0;i<app.model.states.length;i++)for(let j=0;j<3;j++){const c=palette[app.model.states[i]-1];colours.set([c.r,c.g,c.b],i*9+j*3);}
  originalMesh.geometry.setAttribute('color',new THREE.BufferAttribute(colours,3));
  if(highlight)highlight.visible=false;
  drawBorderSegments(after?proposal.border_after:proposal.border_before,after?0xb8ed92:0xffc879);
  $('view-title').textContent=after?'Smoothed junction · preview':'Original junction · before';
}
$('border-preview').onclick=async()=>{
  if(app.busy || app.selected===null)return;
  busy(true,'Smoothing shared paint junction…');clearPreview();
  try {
    app.borderProposal=await request('/api/smooth-preview',{model_id:app.model.model_id,region:app.selected,amount:Number($('border-amount').value),band:Number($('border-band').value)});
    const r=app.borderProposal.smoothing_report;
    $('border-review').hidden=false;
    $('border-report').textContent=`${r.moved_vertices} mesh vertices adjusted · maximum ${r.maximum_movement_mm.toFixed(4)} mm.${r.safety_scale<1?' Movement reduced to protect delicate faces.':''} Compare before and after, then apply or cancel.`;
    borderView(true);$('settings').disabled=true; $('border-amount').disabled=$('border-band').disabled=true;
  }catch(e){notice(e.message,true);}finally{busy(false);if(app.borderProposal){$('border-settings').disabled=false;$('border-preview').disabled=true;$('settings').disabled=true;}}
};
$('border-before').onclick=()=>borderView(false);$('border-after').onclick=()=>borderView(true);
$('border-cancel').onclick=async()=>{
  if(app.busy)return;try{await request('/api/smooth-cancel',{model_id:app.model.model_id});borderView(false);app.borderProposal=null;dispose(borderLines);borderLines=null;$('border-review').hidden=true;$('border-preview').disabled=false; $('border-amount').disabled=$('border-band').disabled=false;setMode('original');busy(false);}catch(e){notice(e.message,true);}
};
async function commitBorder(undo=false){
  if(app.busy)return;const region=app.selected;busy(true,undo?'Undoing smoothing…':'Applying smoothing…');
  try{const payload=await request(undo?'/api/smooth-undo':'/api/smooth-apply',{model_id:app.model.model_id,smooth_id:app.borderProposal?.smooth_id});dispose(borderLines);borderLines=null;mountModel(payload);busy(false);await selectRegion(region);notice(undo?'Smoothing undone.':'Junction smoothing applied. The next cut uses this edited mesh.');}
  catch(e){notice(e.message,true);}finally{$('border-preview').disabled=false; $('border-amount').disabled=$('border-band').disabled=false;busy(false);}
}
$('border-apply').onclick=()=>commitBorder();$('border-undo').onclick=()=>commitBorder(true);

$('fragment-width').oninput=invalidate;

function updateGlueControls(){
  const active=$('cut-method').value==='interface';
  const glueOption=$('fastener').querySelector('option[value="glue"]');glueOption.disabled=!active;
  if(!active)$('fastener').value='none';
  $('glue-controls').hidden=$('fastener').value!=='glue';
  $('connection-status').textContent=$('fastener').value==='glue'?'GLUE KEY':'PLAIN INSERT';
}
$('fastener').onchange=()=>{updateGlueControls();invalidate();};
for(const id of ['glue-width','glue-length','glue-depth','glue-taper','glue-wall'])$(id).oninput=invalidate;
const previousMethodChange=$('cut-method').onchange;
$('cut-method').onchange=()=>{updateGlueControls();previousMethodChange();};

$('fit-target').onchange=invalidate;
