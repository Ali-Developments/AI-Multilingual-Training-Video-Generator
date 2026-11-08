import puppeteer from 'puppeteer-core';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const targetDir = path.resolve(__dirname, '../docs/screenshots/v2');
if (!fs.existsSync(targetDir)) {
  fs.mkdirSync(targetDir, { recursive: true });
}

async function capture() {
  console.log('Connecting to Chrome...');
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1440,900'],
    defaultViewport: { width: 1440, height: 900 },
  });

  const page = await browser.newPage();

  async function clickButtonWithText(targetText) {
    await page.evaluate((text) => {
      const btns = Array.from(document.querySelectorAll('button'));
      const match = btns.find((b) => b.innerText.includes(text));
      if (match) match.click();
    }, targetText);
  }

  // 1. Dashboard
  console.log('Capturing Dashboard...');
  await page.goto('http://localhost:3000/', { waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(targetDir, '01_dashboard.png') });

  // 2. Create Wizard - Content (Step 1)
  console.log('Capturing Create Wizard (Content)...');
  await page.goto('http://localhost:3000/create', { waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 1000));
  await page.screenshot({ path: path.join(targetDir, '02_create_wizard.png') });

  // 3. Create Wizard - Languages (Step 2)
  console.log('Capturing Create Wizard (Languages)...');
  await clickButtonWithText('Next');
  await new Promise((r) => setTimeout(r, 800));
  await page.screenshot({ path: path.join(targetDir, '03_languages_step.png') });

  // 4. Create Wizard - Video Style (Step 3)
  console.log('Capturing Video Style...');
  await clickButtonWithText('Next');
  await new Promise((r) => setTimeout(r, 800));
  await page.screenshot({ path: path.join(targetDir, '04_video_style.png') });

  // 5. Create Wizard - Presenter (Step 4)
  console.log('Capturing Presenter Studio...');
  await clickButtonWithText('Next');
  await new Promise((r) => setTimeout(r, 800));
  await page.screenshot({ path: path.join(targetDir, '05_presenter_studio.png') });

  // 6. Scene Editor & Timeline (proj_v2_phishing_acceptance)
  console.log('Capturing Scene Editor & Timeline...');
  await page.goto('http://localhost:3000/studio/proj_v2_phishing_acceptance', { waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 2000));
  await page.screenshot({ path: path.join(targetDir, '06_scene_editor.png') });
  await page.screenshot({ path: path.join(targetDir, '07_timeline.png') });

  // 7. Final Export Dashboard
  console.log('Capturing Final Export Dashboard...');
  await page.goto('http://localhost:3000/studio/proj_v2_phishing_acceptance/export', { waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 2000));
  await page.screenshot({ path: path.join(targetDir, '08_final_export.png') });

  // 8. Projects Catalog
  console.log('Capturing Projects Catalog...');
  await page.goto('http://localhost:3000/projects', { waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(targetDir, '09_projects_catalog.png') });

  // 9. Hardware & Diagnostics
  console.log('Capturing Settings Diagnostics...');
  await page.goto('http://localhost:3000/settings', { waitUntil: 'networkidle2' });
  await new Promise((r) => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(targetDir, '10_settings_diagnostics.png') });

  await browser.close();
  console.log('All screenshots captured successfully in docs/screenshots/v2!');
}

capture().catch((err) => {
  console.error('Screenshot capture failed:', err);
  process.exit(1);
});
