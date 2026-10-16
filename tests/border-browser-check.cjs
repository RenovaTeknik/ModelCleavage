const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('./browser-runtime.cjs');
(async()=>{const b=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const p=await b.newPage({viewport:{width:1500,height:1100}});const errors=[];p.on('pageerror',e=>errors.push(e.message));try{
 await p.goto('http://127.0.0.1:8765');await p.locator('#file').setInputFiles(path.resolve(__dirname,'fixtures/curved-interface.3mf'));await p.locator('#busy').waitFor({state:'hidden'});await p.locator('.region').filter({hasText:'Filament 2'}).first().click();await p.waitForFunction(()=>!document.getElementById('settings').disabled);
 await p.locator('#border-settings summary').click();await p.locator('#border-preview').click();await p.locator('#border-review').waitFor();assert.ok(await p.locator('#preview').isDisabled());assert.match(await p.locator('#border-report').textContent(),/mesh vertices adjusted/);
 await p.locator('#border-before').click();assert.match(await p.locator('#view-title').textContent(),/before/);await p.locator('#border-after').click();assert.match(await p.locator('#view-title').textContent(),/preview/);
 await p.screenshot({path:path.resolve(__dirname,'../output/border-smoothing-preview.png'),fullPage:true});
 await p.locator('#border-cancel').click();await p.locator('#border-review').waitFor({state:'hidden'});assert.ok(await p.locator('#border-undo').isDisabled());assert.ok(await p.locator('#preview').isEnabled());
 await p.locator('#border-preview').click();await p.locator('#border-review').waitFor();await p.locator('#border-apply').click();await p.waitForFunction(()=>!document.getElementById('border-undo').disabled);assert.ok(await p.locator('#border-review').isHidden());
 await p.locator('#preview').click();await p.locator('#busy').waitFor({state:'hidden',timeout:60000});assert.ok(await p.locator('#validation').isVisible(),await p.locator('#feedback').textContent());
 await p.locator('#border-undo').click();await p.locator('#busy').waitFor({state:'hidden'});assert.ok(await p.locator('#border-undo').isDisabled());assert.ok(await p.locator('#export').isDisabled());assert.match(await p.locator('#feedback').textContent(),/undone/);assert.deepEqual(errors,[]);
 console.log('PASS: smoothing preview, shared boundary overlays, before/after, cancel, apply, cut using edited mesh, undo and export invalidation');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exit(1)});
