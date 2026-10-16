// Optional browser checks use npm Playwright, with an optional local browser override.
const fs = require('node:fs');
const { chromium } = require('playwright');
module.exports.chromium = {
  launch(options = {}) {
    const { executablePath, ...rest } = options;
    const browser = process.env.MODEL_CLEAVAGE_BROWSER || (executablePath && fs.existsSync(executablePath) ? executablePath : undefined);
    return chromium.launch({ ...rest, ...(browser ? { executablePath: browser } : {}) });
  }
};
