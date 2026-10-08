import puppeteer from 'puppeteer-core';
import fs from 'fs';
import path from 'path';

async function runStudioBootstrapTest() {
  console.log('--- STARTING REAL KABSA STUDIO MODE BOOTSTRAP TEST ---');
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--window-size=1600,1000'],
    defaultViewport: { width: 1600, height: 1000 },
  });

  const page = await browser.newPage();

  let alertTriggered = false;
  let alertMessage = '';
  page.on('dialog', async (dialog) => {
    alertTriggered = true;
    alertMessage = dialog.message();
    console.log(`[UNEXPECTED BROWSER DIALOG]: ${alertMessage}`);
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

    async function advanceToStep(targetStep) {
      console.log(`Advancing to Step ${targetStep}...`);
      for (let attempt = 0; attempt < 10; attempt++) {
        const currentStep = await page.evaluate(() => {
          const match = document.body.innerText.match(/Step (\d) of 5/);
          return match ? parseInt(match[1], 10) : 1;
        });
        if (currentStep >= targetStep) {
          console.log(`Reached Step ${currentStep}`);
          return;
        }
        await page.evaluate(() => {
          const btns = Array.from(document.querySelectorAll('button'));
          const cont = btns.find((b) => b.innerText.includes('Continue'));
          if (cont) cont.click();
        });
        await new Promise((r) => setTimeout(r, 600));
      }
      throw new Error(`Failed to advance to Step ${targetStep}`);
    }

    // STEP 1: Content
    console.log('Step 1: Entering Kabsa content...');
    await page.evaluate(() => {
      const inputs = Array.from(document.querySelectorAll('input[type="text"]'));
      if (inputs[0]) inputs[0].value = '';
    });
    const topicInput = (await page.$$('input[type="text"]'))[0];
    await topicInput.type('Saudi Kabsa Preparation Basics');

    const textarea = await page.$('textarea');
    if (textarea) {
      await page.evaluate((el) => { el.value = ''; }, textarea);
      await textarea.type('Saudi Kabsa is made by cooking chicken with onions, tomatoes, traditional Saudi spices, and basmati rice in the seasoned broth.');
    }

    const audienceInput = (await page.$$('input[type="text"]'))[1];
    if (audienceInput) {
      await page.evaluate((el) => { el.value = ''; }, audienceInput);
      await audienceInput.type('Beginner home cooks');
    }

    await clickButtonWithText('30s');
    await new Promise((r) => setTimeout(r, 400));

    await advanceToStep(2);

    // STEP 2: Languages
    console.log('Step 2: Selecting ar-SA language...');
    await page.evaluate(() => {
      const cards = Array.from(document.querySelectorAll('div'));
      const arCard = cards.find((c) => c.innerText && c.innerText.includes('Arabic (Saudi Arabia)'));
      if (arCard) arCard.click();
    });
    await new Promise((r) => setTimeout(r, 400));

    await advanceToStep(3);

    // STEP 3: Video Style
    console.log('Step 3: Selecting Demonstration / Tutorial Style...');
    await page.evaluate(() => {
      const styleCards = Array.from(document.querySelectorAll('div'));
      const demoCard = styleCards.find((c) => c.innerText && c.innerText.includes('Demonstration / Tutorial'));
      if (demoCard) demoCard.click();
    });
    await new Promise((r) => setTimeout(r, 400));

    await advanceToStep(4);

    // STEP 4: Presenter Studio
    console.log('Step 4: Selecting SadTalker Local Engine...');
    await page.evaluate(() => {
      const provCards = Array.from(document.querySelectorAll('div'));
      const sadCard = provCards.find((c) => c.innerText && c.innerText.includes('SadTalker Local'));
      if (sadCard) sadCard.click();
    });
    await new Promise((r) => setTimeout(r, 400));

    await advanceToStep(5);

    // STEP 5: Review & Submit
    console.log('Step 5: Submitting via Studio Mode (Recommended)...');
    await page.waitForFunction(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      return btns.some((b) => b.innerText.includes('Studio Mode'));
    }, { timeout: 10000 });

    await page.evaluate(() => {
      const btns = Array.from(document.querySelectorAll('button'));
      const studioBtn = btns.find((b) => b.innerText.includes('Studio Mode'));
      if (studioBtn) studioBtn.click();
      else throw new Error('Studio Mode button not found');
    });

    // Wait for the full Studio bootstrap (Project created -> Script generated -> Storyboard planned -> Studio navigation)
    console.log('Waiting for Studio bootstrap and navigation to /studio/proj_... (up to 120s)');
    await page.waitForFunction(
      () => window.location.pathname.startsWith('/studio/proj_'),
      { timeout: 120000 }
    );

    const studioUrl = page.url();
    const match = studioUrl.match(/\/studio\/(proj_[a-zA-Z0-9]+)/);
    const projectId = match ? match[1] : null;

    console.log(`Successfully navigated to Studio: ${studioUrl}`);
    console.log(`Bootstrapped Project ID: ${projectId}`);

    // Wait for scenes to load and render on the Studio page
    console.log('Waiting for scenes to load in Studio interface...');
    await page.waitForFunction(
      () => {
        const text = document.body.innerText;
        return text.includes('Scenes (') && !text.includes('Scenes (0)');
      },
      { timeout: 30000 }
    );

    await new Promise((r) => setTimeout(r, 2000));

    // Extract scenes count and scene data from the DOM
    const studioState = await page.evaluate(() => {
      const bodyText = document.body.innerText;
      const scenesMatch = bodyText.match(/Scenes \((\d+)\)/);
      const scenesCount = scenesMatch ? parseInt(scenesMatch[1], 10) : 0;

      const buttons = Array.from(document.querySelectorAll('button')).map((b) => b.innerText.trim());
      const hasReplanButton = buttons.some((b) => b.includes('Re-plan Storyboard'));
      const hasRenderButton = buttons.some((b) => b.includes('Render Video'));

      return {
        scenesCount,
        hasReplanButton,
        hasRenderButton,
        url: window.location.href,
      };
    });

    console.log('\n--- STUDIO INTERFACE STATE ---');
    console.log(`Scenes count in UI: ${studioState.scenesCount}`);
    console.log(`Re-plan Storyboard button present: ${studioState.hasReplanButton}`);
    console.log(`Render Video button present: ${studioState.hasRenderButton}`);

    // Capture screenshot of the generated Kabsa storyboard
    const screenshotPath = 'kabsa_studio_storyboard.png';
    await page.screenshot({ path: screenshotPath, fullPage: true });
    console.log(`Saved screenshot to: ${screenshotPath}`);

    // Verify backend state via API
    console.log('\n--- VERIFYING BACKEND MANIFEST ---');
    const apiRes = await page.evaluate(async (pid) => {
      const res = await fetch(`/api/v1/projects/${pid}`);
      return { ok: res.ok, status: res.status, manifest: await res.json() };
    }, projectId);

    const m = apiRes.manifest;
    console.log(`Manifest script_status: ${m.script_status}`);
    console.log(`Manifest final_script present: ${Boolean(m.final_script)}`);
    console.log(`Manifest scenes count: ${m.final_script?.scenes?.length}`);
    console.log(`Manifest audio_status: ${m.audio_status}`);
    console.log(`Manifest avatar_status: ${m.avatar_status}`);
    console.log(`Manifest composition_status: ${m.composition_status}`);
    console.log(`Manifest final_videos: ${JSON.stringify(m.final_videos)}`);

    // Validations:
    if (alertTriggered) {
      throw new Error(`Unexpected browser alert was triggered: ${alertMessage}`);
    }
    if (!m.final_script || !m.final_script.scenes || m.final_script.scenes.length === 0) {
      throw new Error('final_script was not persisted on backend manifest');
    }
    if (studioState.scenesCount === 0) {
      throw new Error('Studio UI showed 0 scenes');
    }
    if (m.audio_status === 'completed' || Object.keys(m.audio_tracks || {}).length > 0) {
      throw new Error('TTS was unexpectedly executed during Studio preparation');
    }
    if (m.avatar_status === 'completed' || Object.keys(m.avatar_tracks || {}).length > 0) {
      throw new Error('SadTalker was unexpectedly executed during Studio preparation');
    }
    if (m.composition_status === 'completed' || Object.keys(m.final_videos || {}).length > 0) {
      throw new Error('Final Video composition was unexpectedly executed during Studio preparation');
    }

    console.log('\n========================================');
    console.log('REAL KABSA STUDIO BOOTSTRAP PASSED PERFECTLY!');
    console.log(`Project ID: ${projectId}`);
    console.log(`Scenes planned: ${m.final_script.scenes.length}`);
    m.final_script.scenes.forEach((s, i) => {
      console.log(`  Scene ${i + 1}: [${s.media_type} / ${s.layout_type}] ${s.title} (avatar=${s.avatar_enabled})`);
    });
    console.log('========================================\n');

    await browser.close();
    process.exit(0);
  } catch (err) {
    console.error('STUDIO BOOTSTRAP TEST FAILED:', err);
    await page.screenshot({ path: 'kabsa_studio_failure.png' }).catch(() => {});
    await browser.close();
    process.exit(1);
  }
}

runStudioBootstrapTest();
