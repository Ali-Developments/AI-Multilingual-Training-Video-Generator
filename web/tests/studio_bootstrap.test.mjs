import test from 'node:test';
import assert from 'node:assert/strict';

// Tests for Studio Mode bootstrap, button states, render guards, and notifications

function getStoryboardButtonLabel(scenesCount) {
  return scenesCount === 0 ? 'Generate AI Storyboard' : 'Re-plan Storyboard';
}

function isRenderButtonDisabled(manifest, scenesCount, rendering = false) {
  if (rendering) return true;
  if (!manifest || !manifest.final_script) return true;
  if (!scenesCount || scenesCount === 0) return true;
  return false;
}

function getRenderDisabledReason(manifest, scenesCount) {
  if (!manifest?.final_script || !scenesCount || scenesCount === 0) {
    return 'Generate the storyboard before rendering.';
  }
  return null;
}

function formatApiError(errData, fallback = 'Operation failed') {
  if (!errData) return fallback;
  if (typeof errData === 'string') return errData;
  if (typeof errData.detail === 'string') return errData.detail;

  if (Array.isArray(errData.detail)) {
    const formatted = errData.detail
      .map((item) => {
        if (!item) return '';
        if (typeof item === 'string') return item;
        const loc = Array.isArray(item.loc)
          ? item.loc.filter((part) => part !== 'body').join('.')
          : '';
        const msg = item.msg || item.message || JSON.stringify(item);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (formatted.length > 0) return formatted.join('\n');
  }

  if (errData.detail && typeof errData.detail === 'object' && !Array.isArray(errData.detail)) {
    if (typeof errData.detail.message === 'string' && errData.detail.message.trim()) {
      return errData.detail.message;
    }
    if (typeof errData.detail.msg === 'string' && errData.detail.msg.trim()) {
      return errData.detail.msg;
    }
  }

  if (typeof errData.message === 'string' && errData.message.trim()) return errData.message;
  if (typeof errData.error === 'string' && errData.error.trim()) return errData.error;

  try {
    const str = JSON.stringify(errData);
    return str !== '{}' ? str : fallback;
  } catch {
    return fallback;
  }
}

test('6. Generate Storyboard label shown when scenes == 0', () => {
  const label = getStoryboardButtonLabel(0);
  assert.equal(label, 'Generate AI Storyboard');
});

test('7. Re-plan label shown only when storyboard exists', () => {
  const label1 = getStoryboardButtonLabel(1);
  assert.equal(label1, 'Re-plan Storyboard');

  const label5 = getStoryboardButtonLabel(5);
  assert.equal(label5, 'Re-plan Storyboard');
});

test('8. Render disabled when no scenes or final_script missing', () => {
  // Empty manifest
  assert.equal(isRenderButtonDisabled(null, 0), true);

  // Manifest with no final_script
  const noScript = { project_id: 'p1', final_script: null };
  assert.equal(isRenderButtonDisabled(noScript, 0), true);
  assert.equal(getRenderDisabledReason(noScript, 0), 'Generate the storyboard before rendering.');

  // Manifest with final_script but 0 scenes
  const emptyScenes = { project_id: 'p2', final_script: { scenes: [] } };
  assert.equal(isRenderButtonDisabled(emptyScenes, 0), true);
  assert.equal(getRenderDisabledReason(emptyScenes, 0), 'Generate the storyboard before rendering.');

  // Manifest with final_script and scenes > 0
  const readyManifest = { project_id: 'p3', final_script: { scenes: [{ scene_id: 's1' }] } };
  assert.equal(isRenderButtonDisabled(readyManifest, 1), false);
  assert.equal(getRenderDisabledReason(readyManifest, 1), null);
});

test('Structured API error detail with PROJECT_NOT_FOUND formats cleanly', () => {
  const errPayload = {
    detail: {
      code: 'PROJECT_NOT_FOUND',
      message: "Project 'proj_missing' not found.",
    },
  };
  const msg = formatApiError(errPayload);
  assert.equal(msg, "Project 'proj_missing' not found.");
  assert.ok(!msg.includes('[object Object]'));
});

test('Structured API error detail with FINAL_SCRIPT_MISSING formats cleanly', () => {
  const errPayload = {
    detail: {
      code: 'FINAL_SCRIPT_MISSING',
      message: 'Canonical script missing. Generate script before planning storyboard.',
    },
  };
  const msg = formatApiError(errPayload);
  assert.equal(msg, 'Canonical script missing. Generate script before planning storyboard.');
  assert.ok(!msg.includes('[object Object]'));
});
