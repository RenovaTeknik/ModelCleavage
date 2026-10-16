if (!process.env.MODEL_CLEAVAGE_REPAIR_SAMPLE) { console.log('SKIP: set MODEL_CLEAVAGE_REPAIR_SAMPLE for the private Remy repair regression.'); process.exit(0); }
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('./browser-runtime.cjs');
(async () => {
  const executablePath = ['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].find(p => fs.existsSync(p));
  const browser = await chromium.launch({ executablePath, headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const root = path.resolve(__dirname, '..');
  const sample = process.env.MODEL_CLEAVAGE_REPAIR_SAMPLE;
  const before = require('node:crypto').createHash('sha256').update(fs.readFileSync(sample)).digest('hex');
  try {
    await page.goto('http://127.0.0.1:8765', { waitUntil: 'networkidle' });
    await page.locator('#file').setInputFiles(sample);
    await page.locator('#diagnostics').waitFor({ state: 'visible', timeout: 60000 });
    assert.ok((await page.locator('#diagnostic-summary').textContent()).includes('814 non-manifold'));
    await page.locator('#busy').waitFor({ state: 'hidden' });
    assert.ok(await page.locator('#preview').isDisabled());
    await page.screenshot({ path: path.join(root, 'output', 'remy-problem-highlights.png'), fullPage: true });
    await page.getByRole('button', { name: 'Preview proposed repair' }).click();
    await page.locator('#repair-review').waitFor({ state: 'visible', timeout: 120000 });
    await page.locator('#busy').waitFor({ state: 'hidden' });
    assert.ok(await page.locator('#repair-approve').isDisabled());
    assert.ok(await page.locator('#preview').isDisabled());
    assert.ok((await page.locator('#repair-summary').textContent()).includes('430'));
    await page.screenshot({ path: path.join(root, 'output', 'remy-repair-proposal.png'), fullPage: true });
    await page.getByRole('button', { name: 'Show original', exact: true }).click();
    await page.getByRole('button', { name: 'Show proposal', exact: true }).click();
    await page.getByRole('button', { name: 'Cancel · keep original' }).click();
    await page.locator('#repair-review').waitFor({ state: 'hidden' });
    assert.ok(await page.locator('#diagnostics').isVisible());
    assert.equal(require('node:crypto').createHash('sha256').update(fs.readFileSync(sample)).digest('hex'), before);
    assert.deepEqual(errors, []);
    console.log('PASS: Remy inspection, 814-edge highlights, geometry/colour change preview, explicit approval gate, compare views, cancel, source hash unchanged. No repair approved.');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
