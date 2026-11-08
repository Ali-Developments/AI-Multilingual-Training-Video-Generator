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

  const networkRequests = [];
  const notFoundRequests = [];
  const renderRequests = [];

  page.on('request', (req) => {
    const url = req.url();
    networkRequests.push({ method: req.method(), url });
    if (url.includes('/render')) {
      console.log(`[NETWORK EVENT] Render request sent: ${req.method()} ${url}`);
      renderRequests.push({ method: req.method(), url });
    }
  });

  page.on('response', (res) => {
    if (res.status() === 404) {
      console.log(`[404 DETECTED] ${res.url()}`);
      notFoundRequests.push(res.url());
    }
  });

  page.on('console', (msg) => {
    const text = msg.text();
    if (text.includes('Error') || text.includes('error') || text.includes('Render') || text.includes('render')) {
      console.log(`[BROWSER CONSOLE] ${msg.type()}: ${text}`);
    }
  });

  console.log('Navigating to http://localhost:3000/studio/proj_b1c9c49c8259...');
  await page.goto('http://localhost:3000/studio/proj_b1c9c49c8259', { waitUntil: 'networkidle2', timeout: 30000 });

  console.log('Page loaded successfully.');
  await page.screenshot({ path: 'pre_render_studio.png' });

  // 1. Verify 404s
  const scene404s = notFoundRequests.filter((url) => url.includes('.mp4'));
  console.log(`Pre-render MP4 404 count: ${scene404s.length}`);
  if (scene404s.length > 0) {
    console.error('FAILED: Pre-render 404s detected on MP4s:', scene404s);
  } else {
    console.log('SUCCESS: Zero premature MP4 404s detected!');
  }

  // 2. Verify placeholder on page
  const placeholderText = await page.evaluate(() => {
    return document.body.innerText.includes('Scene not rendered yet');
  });
  console.log(`Placeholder "Scene not rendered yet" visible: ${placeholderText}`);

  // 3. Find and click "Render Video"
  console.log('Locating "Render Video" button...');
  const renderButton = await page.waitForSelector('button', { timeout: 5000 });
  const clicked = await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button'));
    const btn = buttons.find((b) => b.textContent && b.textContent.includes('Render Video'));
    if (btn) {
      btn.click();
      return true;
    }
    return false;
  });

  console.log(`Render Video clicked: ${clicked}`);
  if (!clicked) {
    console.error('Could not find Render Video button!');
    await browser.close();
    process.exit(1);
  }

  // Wait 3 seconds to confirm request fired
  await new Promise((r) => setTimeout(r, 3000));
  console.log(`Render requests intercepted: ${renderRequests.length}`);

  await page.screenshot({ path: 'rendering_studio_progress.png' });
  await browser.close();
  console.log('Pre-render checks and Render Video click verified.');
}

run().catch((err) => {
  console.error('Error running test:', err);
  process.exit(1);
});
