const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('./browser-runtime.cjs');
(async()=>{const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));try{
 await page.goto('http://127.0.0.1:8765',{waitUntil:'networkidle'});
 await page.locator('#file').setInputFiles(path.resolve(__dirname,'fixtures/curved-interface.3mf'));
 await page.locator('#model-name').filter({hasText:'curved-interface.3mf'}).waitFor();await page.locator('#busy').waitFor({state:'hidden'});
 await page.locator('.region').filter({hasText:'Filament 2'}).first().click();
 await page.waitForFunction(()=>!document.getElementById('settings').disabled);
 assert.equal(await page.locator('#cut-method').inputValue(),'interface');assert.equal(await page.locator('#direction').inputValue(),'+Z');assert.ok(await page.locator('#plane-controls').isHidden());assert.ok(await page.locator('#side-clearance').isEnabled());
 await page.getByRole('button',{name:'Preview cut'}).click();await page.locator('#busy').waitFor({state:'hidden',timeout:180000});assert.ok(await page.locator('#validation').isVisible(), await page.locator('#feedback').textContent());assert.match(await page.locator('#checks').textContent(),/Interface profile/);
 await page.locator('#explode').fill('5');await page.locator('#explode').dispatchEvent('input');await page.screenshot({path:require('node:path').resolve(__dirname,'../output/interface-browser.png'),fullPage:true});
 await page.locator('#settings summary').click();await page.locator('#side-clearance').fill('0.15');await page.locator('#side-clearance').dispatchEvent('input');await page.locator('#depth-clearance').fill('0.2');await page.locator('#depth-clearance').dispatchEvent('input');assert.ok(await page.locator('#export').isDisabled());
 await page.getByRole('button',{name:'Preview cut'}).click();await page.locator('#busy').waitFor({state:'hidden',timeout:180000});assert.ok(await page.locator('#validation').isVisible(), await page.locator('#feedback').textContent());
 const download=page.waitForEvent('download');await page.getByRole('button',{name:'Save export'}).click();await(await download).saveAs('cutting-engine-app/output/interface-browser-export.zip');await page.locator('#busy').waitFor({state:'hidden'});
 await page.locator('#cut-method').selectOption('planar');await page.waitForFunction(()=>!document.getElementById('settings').disabled);assert.ok(await page.locator('#plane-controls').isVisible());assert.ok(await page.locator('#export').isDisabled());
 await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);console.log('PASS: interface default, direction suggestion, hidden manual plane, side fit enabled, curved solid preview, depth fit, export, method-change invalidation, responsive UI');
}finally{await browser.close();}})().catch(e=>{console.error(e);process.exit(1)});
