const assert=require('node:assert/strict'),path=require('node:path');
const {chromium}=require('./browser-runtime.cjs');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(e.message));try{
 await page.goto('http://127.0.0.1:8765');
 await page.locator('#file').setInputFiles(path.resolve(__dirname,'fixtures/cancellable-sphere.3mf'));await page.locator('#busy').waitFor({state:'hidden'});
 await page.locator('.region').filter({hasText:'Filament 2'}).first().click();await page.waitForFunction(()=>!document.getElementById('settings').disabled);
 const response=page.waitForResponse(r=>r.url().endsWith('/api/preview')&&r.request().method()==='POST');
 await page.locator('#preview').click();const job=await(await response).json();assert.ok(job.job_id);
 await page.locator('#cancel-cut').waitFor({state:'visible'});await page.waitForFunction(()=>/Sweeping complete painted feature|Combining complete feature sweep|Splitting model/.test(document.getElementById('busy-text').textContent),{},{timeout:60000});assert.ok(await page.locator('#open-file').isDisabled());
 const health=await page.request.get('http://127.0.0.1:8765/api/health',{timeout:3000});assert.ok(health.ok());
 const start=Date.now();await page.locator('#cancel-cut').click();await page.locator('#busy').waitFor({state:'hidden',timeout:10000});
 assert.ok(Date.now()-start<5000);assert.match(await page.locator('#feedback').textContent(),/Cut cancelled/);assert.ok(await page.locator('#preview').isEnabled());assert.ok(await page.locator('#export').isDisabled());assert.equal(await page.locator('.region.active').count(),1);
 assert.deepEqual(errors,[]);console.log('PASS: active cut cancellation within 5 seconds, responsive health endpoint, loaded model and selection retained, no export, preview can restart');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
