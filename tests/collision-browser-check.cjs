const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const {chromium}=require('./browser-runtime.cjs');
(async()=>{const b=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const p=await b.newPage({viewport:{width:1500,height:1000}});const errors=[];p.on('pageerror',e=>errors.push(e.message));try{
 await p.goto('http://127.0.0.1:8765');let model;await p.route('**/api/load',async route=>{const response=await route.fetch();model=await response.json();await route.fulfill({response});});await p.locator('#file').setInputFiles(path.resolve(__dirname,'fixtures/curved-interface.3mf'));await p.locator('#busy').waitFor({state:'hidden'});
 await p.locator('.region').filter({hasText:'Filament 2'}).first().click();await p.waitForFunction(()=>!document.getElementById('settings').disabled);
 const diagnostic=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/collision-diagnostic.json'),'utf8'));
 await p.route('**/api/preview',r=>r.fulfill({json:{job_id:'diagnostic-fixture',state:'running'}}));await p.route('**/api/job-status',r=>r.fulfill({json:diagnostic}));
 await p.locator('#preview').click();await p.locator('#busy').waitFor({state:'hidden'});assert.ok(await p.locator('#collision-diagnostics').isVisible());assert.ok(await p.locator('#export').isDisabled());assert.ok(await p.locator('#validation').isHidden());assert.match(await p.locator('#collision-summary').textContent(),/0.50000/);
 await p.locator('#focus-collision').click();assert.match(await p.locator('#view-title').textContent(),/Collision at 2.000 mm/);await p.screenshot({path:path.resolve(__dirname,'../output/collision-browser.png'),fullPage:true});
 await p.locator('#original-view').click();assert.equal(await p.locator('#view-title').textContent(),'Painted surface');await p.locator('#cut-view').click();assert.match(await p.locator('#view-title').textContent(),/Collision/);
 const blocked=await p.request.post('http://127.0.0.1:8765/api/export',{data:{model_id:model.model_id,result_id:'not-a-valid-result'}});assert.equal(blocked.status(),400);
 await p.locator('#depth').fill('3');await p.locator('#depth').dispatchEvent('input');assert.ok(await p.locator('#collision-diagnostics').isHidden());assert.ok(await p.locator('#cut-view').isDisabled());assert.ok(await p.locator('#export').isDisabled());assert.deepEqual(errors,[]);
 console.log('PASS: measured collision preview, focus, original/diagnostic switching, no valid-cut checkmarks, backend export blocked, settings clear stale diagnostics');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exit(1)});
