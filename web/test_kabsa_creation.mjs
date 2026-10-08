import puppeteer from 'puppeteer-core';

async function runKabsaTest() {
  console.log('Launching Chrome via puppeteer-core...');
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1440,900'],
    defaultViewport: { width: 1440, height: 900 },
  });

  const page = await browser.newPage();

  // Listen for console messages and dialogs
  let alertTriggered = false;
  let alertMessage = '';
  page.on('dialog', async (dialog) => {
    alertTriggered = true;
    alertMessage = dialog.message();
    console.log(`[BROWSER DIALOG]: ${alertMessage}`);
    await dialog.dismiss();
  });

  page.on('console', (msg) => {
    if (msg.type() === 'error') {
      console.log(`[BROWSER ERROR]: ${msg.text()}`);
    }
  });

  try {
    console.log('Navigating to http://localhost:3000/create...');
    await page.goto('http://localhost:3000/create', { waitUntil: 'networkidle2' });
    await new Promise((r) => setTimeout(r, 1000));

    // Helper to click button with text
    async function clickButtonWithText(text) {
      const clicked = await page.evaluate((targetText) => {
        const btns = Array.from(document.querySelectorAll('button'));
        const match = btns.find((b) => b.innerText.includes(targetText));
        if (match) {
          match.click();
          return true;
        }
        return false;
      }, text);
      if (!clicked) {
        throw new Error(`Button with text "${text}" not found`);
      }
    }

    // STEP 1: Content
    console.log('Filling Step 1: Content...');
    // Clear and type Topic
    await page.evaluate(() => {
      const inputs = Array.from(document.querySelectorAll('input[type="text"]'));
      if (inputs[0]) {
        inputs[0].value = '';
      }
    });
    const topicInput = (await page.$$('input[type="text"]'))[0];
    await topicInput.type('Saudi Kabsa Preparation Basics');

    // Fill Educational Content
    const textarea = await page.$('textarea');
    if (textarea) {
      await page.evaluate((el) => { el.value = ''; }, textarea);
      await textarea.type('Saudi Kabsa is made by cooking chicken with onions, tomatoes, traditional Saudi spices, and basmati rice in the seasoned broth.');
    }

    // Fill Audience
    const audienceInput = (await page.$$('input[type="text"]'))[1];
    if (audienceInput) {
      await page.evaluate((el) => { el.value = ''; }, audienceInput);
      await audienceInput.type('Beginner home cooks');
    }

    // Click 30s preset
    await clickButtonWithText('30s');
    await new Promise((r) => setTimeout(r, 500));

    // Click Continue to Step 2
    console.log('Advancing to Step 2...');
    await clickButtonWithText('Continue');
    await new Promise((r) => setTimeout(r, 800));

    // STEP 2: Languages
    console.log('Configuring Step 2: Languages...');
    // Ensure ar-SA is selected
    await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll('div'));
      const arCard = cards.find((c) => c.innerText && c.innerText.includes('Arabic (Saudi Arabia)'));
      if (arCard) arCard.click();
    });
    await new Promise((r) => setTimeout(r, 500));

    // Click Continue to Step 3
    console.log('Advancing to Step 3...');
    await clickButtonWithText('Continue');
    await new Promise((r) => setTimeout(r, 800));

    // STEP 3: Video Style
    console.log('Selecting Step 3: Demonstration / Tutorial Style...');
    await page.evaluate(() => {
      const styleCards = Array.from(document.querySelectorAll('div'));
      const demoCard = styleCards.find((c) => c.innerText && c.innerText.includes('Demonstration / Tutorial'));
      if (demoCard) demoCard.click();
    });
    await new Promise((r) => setTimeout(r, 500));

    // Click Continue to Step 4
    console.log('Advancing to Step 4...');
    await clickButtonWithText('Continue');
    await new Promise((r) => setTimeout(r, 800));

    // STEP 4: Presenter Studio
    console.log('Selecting Step 4: SadTalker Local Engine...');
    await page.evaluate(() => {
      const provCards = Array.from(document.querySelectorAll('div'));
      const sadCard = provCards.find((c) => c.innerText && c.innerText.includes('SadTalker Local'));
      if (sadCard) sadCard.click();
    });
    await new Promise((r) => setTimeout(r, 500));

    // Click Continue to Step 5
    console.log('Advancing to Step 5...');
    await clickButtonWithText('Continue');
    await new Promise((r) => setTimeout(r, 1000));

    // STEP 5: Review & Submit
    console.log('Submitting Project in Step 5: Studio Mode...');
    await clickButtonWithText('Studio Mode (Recommended)');

    // Wait for navigation to /studio/proj_...
    console.log('Waiting for URL to change to /studio/proj_...');
    await page.waitForFunction(
      () => window.location.pathname.startsWith('/studio/proj_'),
      { timeout: 15000 }
    );

    const finalUrl = page.url();
    const match = finalUrl.match(/\/studio\/(proj_[a-zA-Z0-9]+)/);
    const projId = match ? match[1] : null;

    console.log(`\n========================================`);
    console.log(`SUCCESS! Created Project: ${projId}`);
    console.log(`Final URL: ${finalUrl}`);
    console.log(`Browser Alert Triggered: ${alertTriggered}`);
    console.log(`========================================\n`);

    if (alertTriggered) {
      throw new Error(`Unexpected browser alert was triggered: ${alertMessage}`);
    }

    if (!projId) {
      throw new Error(`Failed to extract project ID from final URL: ${finalUrl}`);
    }

    // Verify project exists in API
    const apiRes = await page.evaluate(async (id) => {
      const res = await fetch(`/api/v1/projects/${id}`);
      return { ok: res.ok, status: res.status, data: await res.json() };
    }, projId);

    console.log(`API verification for ${projId}: status=${apiRes.status}, topic=${apiRes.data.source_request.topic}`);
    console.log('Style:', apiRes.data.source_request.video_style);
    console.log('Avatar Provider:', apiRes.data.avatar_provider);

    await browser.close();
    process.exit(0);
  } catch (err) {
    console.error('KABSA CREATION TEST FAILED:', err);
    await page.screenshot({ path: 'kabsa_failure_screenshot.png' }).catch(() => {});
    await browser.close();
    process.exit(1);
  }
}

runKabsaTest();
