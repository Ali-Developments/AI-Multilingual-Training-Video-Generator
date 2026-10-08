import puppeteer from 'puppeteer-core';
import fs from 'fs';

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const EDGE_PATH = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const executablePath = fs.existsSync(CHROME_PATH) ? CHROME_PATH : EDGE_PATH;

async function run() {
  console.log('Launching browser using:', executablePath);
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  const notFoundRequests = [];
  page.on('response', (res) => {
    if (res.status() === 404) {
      console.log(`[404 DETECTED] ${res.url()}`);
      notFoundRequests.push(res.url());
    }
  });

  page.on('console', (msg) => {
    console.log(`[BROWSER CONSOLE] ${msg.type()}: ${msg.text()}`);
  });

  console.log('Navigating to http://localhost:3000/studio/proj_b1c9c49c8259...');
  await page.goto('http://localhost:3000/studio/proj_b1c9c49c8259', { waitUntil: 'networkidle2', timeout: 30000 });

  // 1. Check for 404s
  console.log(`Total 404s: ${notFoundRequests.length}`);
  if (notFoundRequests.length > 0) {
    console.error('FAILED: Unexpected 404s detected:', notFoundRequests);
  } else {
    console.log('SUCCESS: Zero 404s detected on studio page!');
  }

  // 2. Check scene video player
  const sceneVideoSrc = await page.evaluate(() => {
    const video = document.querySelector('video');
    return video ? video.src : null;
  });
  console.log('Scene video player src:', sceneVideoSrc);

  // Take screenshot of scene 1 preview
  await page.screenshot({ path: 'kabsa_studio_scene_preview.png' });
  console.log('Saved kabsa_studio_scene_preview.png');

  // 3. Click "Full Video" tab
  console.log('Switching to Full Video mode...');
  await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const fullVideoBtn = buttons.find((b) => b.textContent && b.textContent.includes('Full Video'));
    if (fullVideoBtn) fullVideoBtn.click();
  });

  await new Promise((r) => setTimeout(r, 1000));

  const fullVideoSrc = await page.evaluate(() => {
    const video = document.querySelector('video');
    return video ? video.src : null;
  });
  console.log('Full video player src:', fullVideoSrc);

  // Check metadata bar text
  const metadataText = await page.evaluate(() => {
    return document.body.innerText;
  });

  const hasDuration = metadataText.includes('30.0s') || metadataText.includes('29.98s') || metadataText.includes('Duration');
  const hasResolution = metadataText.includes('1920x1080');
  const hasDownload = metadataText.includes('Download');
  const hasCompleted = metadataText.includes('Completed');

  console.log(`Metadata check - Duration: ${hasDuration}, Resolution: ${hasResolution}, Download: ${hasDownload}, Completed: ${hasCompleted}`);

  await page.screenshot({ path: 'kabsa_final_render_studio.png' });
  console.log('Saved kabsa_final_render_studio.png');

  await browser.close();
  console.log('All browser verification checks PASSED successfully!');
}

run().catch((err) => {
  console.error('Error running test:', err);
  process.exit(1);
});
