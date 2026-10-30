import { chromium } from '/private/tmp/node_modules/playwright/index.mjs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import * as fs from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const widths = [
  { name: '390', width: 390, height: 844 },
  { name: '834', width: 834, height: 1112 },
  { name: '1440', width: 1440, height: 900 }
];

async function takeScreenshots() {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  
  for (const { name, width, height } of widths) {
    const page = await context.newPage();
    await page.setViewportSize({ width, height });
    
    // Navigate to the entry screen
    await page.goto('http://localhost:8080');
    
    // Wait for the app to load
    await page.waitForSelector('.entry-stack', { timeout: 5000 });
    
    // Take screenshot
    const screenshotPath = join(__dirname, `ui-${name}.png`);
    await page.screenshot({ path: screenshotPath, fullPage: false });
    
    console.log(`Screenshot saved: ${screenshotPath}`);
    await page.close();
  }
  
  await browser.close();
}

takeScreenshots().catch(console.error);
