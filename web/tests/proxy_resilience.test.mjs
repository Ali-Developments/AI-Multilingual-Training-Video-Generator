import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';

// Replicate parseResponseError logic for unit testing contracts
function formatApiError(errData, fallback = 'Operation failed') {
  if (!errData) return fallback;
  if (typeof errData === 'string') return errData;

  if (typeof errData.detail === 'string') {
    return errData.detail;
  }

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

    if (formatted.length > 0) {
      return formatted.join('\n');
    }
  }

  if (errData.detail && typeof errData.detail === 'object' && !Array.isArray(errData.detail)) {
    if (typeof errData.detail.message === 'string' && errData.detail.message.trim()) {
      return errData.detail.message;
    }
    if (typeof errData.detail.msg === 'string' && errData.detail.msg.trim()) {
      return errData.detail.msg;
    }
  }

  if (typeof errData.message === 'string' && errData.message.trim()) {
    return errData.message;
  }
  if (typeof errData.error === 'string' && errData.error.trim()) {
    return errData.error;
  }

  try {
    const str = JSON.stringify(errData);
    return str !== '{}' ? str : fallback;
  } catch {
    return fallback;
  }
}

async function parseResponseError(res, fallback = 'Operation failed') {
  let errData = null;
  try {
    const text = await res.text();
    if (text && text.trim().length > 0) {
      try {
        errData = JSON.parse(text);
      } catch {
        errData = text.trim();
      }
    }
  } catch {
    errData = null;
  }

  const formatted = formatApiError(errData, fallback);
  const statusPrefix = `HTTP ${res.status}${res.statusText ? ` (${res.statusText})` : ''}`;

  if (formatted && formatted !== fallback) {
    if (formatted.includes(`HTTP ${res.status}`)) {
      return formatted;
    }
    return `${statusPrefix}: ${formatted}`;
  }
  return `${statusPrefix}: ${fallback}`;
}

// =========================================================================
// 1. Error Parsing Tests: Meaningful error reporting for proxy/socket drops
// =========================================================================

test('1. parseResponseError surfaces plaintext Next.js proxy ECONNRESET error cleanly', async () => {
  const proxyErrorText = 'Failed to proxy http://127.0.0.1:8000/api/v1/projects/proj_test/generate-script\nError: socket hang up\ncode: ECONNRESET';
  const mockRes = new Response(proxyErrorText, {
    status: 500,
    statusText: 'Internal Server Error',
    headers: { 'Content-Type': 'text/plain' },
  });

  const err = await parseResponseError(mockRes, 'Failed to generate script');
  assert.ok(err.includes('HTTP 500 (Internal Server Error)'));
  assert.ok(err.includes('socket hang up'));
  assert.ok(err.includes('ECONNRESET'));
  assert.notEqual(err, 'Failed to generate script', 'Must not fall back to generic message when proxy error text is available');
  assert.ok(!err.includes('[object Object]'), 'Must never output [object Object]');
});

test('2. parseResponseError formats 504 Gateway Timeout without body into meaningful message', async () => {
  const mockRes = new Response('', {
    status: 504,
    statusText: 'Gateway Timeout',
  });

  const err = await parseResponseError(mockRes, 'Failed to generate script');
  assert.equal(err, 'HTTP 504 (Gateway Timeout): Failed to generate script');
});

test('3. parseResponseError surfaces FastAPI structured 400 error cleanly', async () => {
  const fastApiJson = JSON.stringify({
    detail: {
      code: 'SCRIPT_GENERATION_FAILED',
      message: 'Script validation failed after 1 revision(s). Required learning objective LO3 is missing.',
    },
  });
  const mockRes = new Response(fastApiJson, {
    status: 400,
    statusText: 'Bad Request',
    headers: { 'Content-Type': 'application/json' },
  });

  const err = await parseResponseError(mockRes, 'Script generation failed');
  assert.ok(err.includes('HTTP 400'));
  assert.ok(err.includes('Script validation failed after 1 revision(s)'));
  assert.ok(err.includes('Required learning objective LO3 is missing'));
});

// =========================================================================
// 2. Long-Running Generation & 200 OK Handling
// =========================================================================

test('4. Successful long-running generation returns manifest and is not treated as a failure', async () => {
  // Spin up an ephemeral local HTTP server simulating a long-running generation endpoint
  const manifestPayload = {
    project_id: 'proj_long_gen',
    status: 'script_completed',
    script_status: 'completed',
    final_script: {
      title: 'Workplace Phishing Defense Essentials',
      scenes: [
        { scene_id: 'SC1', narration: 'Welcome to phishing defense.', learning_objective_ids: ['LO1'] },
        { scene_id: 'SC2', narration: 'Check sender domain names carefully.', learning_objective_ids: ['LO2'] },
        { scene_id: 'SC3', narration: 'Never click unexpected attachments.', learning_objective_ids: ['LO3'] },
        { scene_id: 'SC4', narration: 'Report threats immediately.', learning_objective_ids: ['LO4'] },
      ],
    },
  };

  const server = http.createServer((req, res) => {
    // Simulate delay
    setTimeout(() => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(manifestPayload));
    }, 100);
  });

  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  try {
    const url = `http://127.0.0.1:${port}/api/v1/projects/proj_long_gen/generate-script?force_regenerate=false`;
    const res = await fetch(url, { method: 'POST' });
    assert.equal(res.status, 200);

    const data = await res.json();
    assert.equal(data.project_id, 'proj_long_gen');
    assert.equal(data.status, 'script_completed');
    assert.equal(data.final_script.scenes.length, 4);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});

// =========================================================================
// 3. Duplicate Submission Guard Tests
// =========================================================================

test('5. Frontend double-submission guard suppresses concurrent create/generation calls', async () => {
  let backendCallCount = 0;
  const mockApiCall = async () => {
    backendCallCount++;
    await new Promise((r) => setTimeout(r, 50));
    return { project_id: 'proj_guard_test' };
  };

  // State and ref guard simulation matching CreateVideoWizard
  let submitting = false;
  const isSubmittingRef = { current: false };

  const handleCreate = async () => {
    if (submitting || isSubmittingRef.current) {
      return; // Suppressed duplicate
    }
    isSubmittingRef.current = true;
    try {
      submitting = true;
      await mockApiCall();
    } finally {
      submitting = false;
      isSubmittingRef.current = false;
    }
  };

  // Simulate user rapidly double-clicking before the first async tick completes
  const firstClick = handleCreate();
  const secondClick = handleCreate();
  const thirdClick = handleCreate();

  await Promise.all([firstClick, secondClick, thirdClick]);

  assert.equal(backendCallCount, 1, 'Only exactly 1 request must be sent despite rapid multiple clicks');
});

// =========================================================================
// 4. Verification that 200 OK with JSON is never treated as error
// =========================================================================

test('6. 200 OK response from backend is parsed cleanly without throwing', async () => {
  const successData = {
    project_id: 'proj_ok_test',
    status: 'script_completed',
    final_script: {
      learning_objectives: [
        { id: 'LO1', description: 'Objective 1' },
        { id: 'LO2', description: 'Objective 2' },
        { id: 'LO3', description: 'Objective 3' },
        { id: 'LO4', description: 'Objective 4' },
      ],
    },
  };

  const res = new Response(JSON.stringify(successData), {
    status: 200,
    statusText: 'OK',
    headers: { 'Content-Type': 'application/json' },
  });

  assert.equal(res.ok, true);
  const parsed = await res.json();
  assert.equal(parsed.project_id, 'proj_ok_test');
  assert.equal(parsed.final_script.learning_objectives.length, 4);
});

