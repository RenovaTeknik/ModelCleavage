const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('./browser-runtime.cjs');

(async () => {
  const root = path.resolve(__dirname, '..');
  const executablePath = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find(p => fs.existsSync(p));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}), args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 }, acceptDownloads: true });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  try {
    await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
    await page.getByRole('button', { name: 'Load BasicShapes example' }).click();
    await page.locator('#model-name').filter({ hasText: 'BasicShapes001.3mf' }).waitFor({ timeout: 60000 });
    await page.locator('#busy').waitFor({ state: 'hidden' });
    assert.ok(await page.locator('.region').count() >= 11);
    await page.screenshot({ path: path.join(root, 'output', 'viewer-loaded.png'), fullPage: true });
    // Verified camera/view coordinates: click the black protrusion in the 3D canvas.
    await page.mouse.click(790, 700);
    await page.waitForFunction(() => document.getElementById('selection-name').textContent.includes('Filament 3 · area 4'));
    await page.waitForFunction(() => document.getElementById('direction').value === '+X');
    await page.locator('#cut-method').selectOption('planar');
    await page.locator('#busy').waitFor({ state: 'hidden' });
    await page.locator('.region').filter({ hasText: 'Filament 2 · area 2' }).first().click();
    await page.waitForFunction(() => document.getElementById('plane').value === '-78');
    assert.equal(await page.locator('#direction').inputValue(), '-Y');
    await page.getByRole('button', { name: 'Preview cut' }).click();
    await page.locator('#validation').waitFor({ state: 'visible', timeout: 60000 });
    assert.ok((await page.locator('#checks').textContent()).includes('Closed solids'));
    await page.locator('#explode').fill('35');
    await page.locator('#explode').dispatchEvent('input');
    assert.equal(await page.locator('#explode-value').textContent(), '35 mm');
    await page.screenshot({ path: path.join(root, 'output', 'viewer-exploded.png'), fullPage: true });
    await page.locator('#depth').fill('3');
    await page.locator('#depth').dispatchEvent('input');
    assert.ok(await page.locator('#export').isDisabled());
    await page.locator('#settings summary').click();
    await page.locator('#side-clearance').fill('0.2');
    await page.locator('#side-clearance').dispatchEvent('input');
    await page.getByRole('button', { name: 'Preview cut' }).click();
    await page.locator('#validation').waitFor({ state: 'visible', timeout: 60000 });
    assert.ok((await page.locator('#checks').textContent()).includes('intentional fit gap'));
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Save export' }).click();
    const saved = await download;
    await saved.saveAs(path.join(root, 'output', 'browser-verified-export.zip'));
    assert.ok(fs.statSync(path.join(root, 'output', 'browser-verified-export.zip')).size > 1000);
    await page.locator('#busy').waitFor({ state: 'hidden' });
    await page.getByRole('button', { name: 'Original', exact: true }).click();
    await page.locator('.region').filter({ hasText: 'Filament 4 · area 3' }).first().click();
    await page.waitForFunction(() => document.getElementById('plane').value === '100');
    await page.getByRole('button', { name: 'Preview cut' }).click();
    await page.locator('#validation').waitFor({ state: 'visible', timeout: 60000 });
    await page.locator('#explode').fill('30');
    await page.locator('#explode').dispatchEvent('input');
    await page.screenshot({ path: path.join(root, 'output', 'viewer-top-edge-repaired.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(root, 'output', 'viewer-mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log('PASS: load, 3D ray selection, list selection, solid preview, separation, dirty-state export prevention, tolerance preview, export download, responsive layout, no browser errors');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
