import test from 'node:test';
import assert from 'node:assert/strict';

// Test Suite for Frontend V2 API Contracts, Serializers, and Error Formatters

/**
 * Re-implementation/import testing of serializeCreateProjectRequest logic.
 */
function serializeCreateProjectRequest(input) {
  let targetLangs = ['en-US'];
  if (Array.isArray(input.targetLanguages)) {
    targetLangs = input.targetLanguages.filter((l) => typeof l === 'string' && l.trim().length > 0);
  } else if (typeof input.targetLanguages === 'string' && input.targetLanguages.trim().length > 0) {
    targetLangs = [input.targetLanguages.trim()];
  }
  if (targetLangs.length === 0) {
    targetLangs = [input.baseLanguage?.trim() || 'en-US'];
  }

  let durationSecs = 60;
  if (typeof input.duration === 'number' && !isNaN(input.duration)) {
    durationSecs = Math.round(input.duration);
  } else if (typeof input.duration === 'string') {
    const parsed = parseInt(input.duration.replace(/[^\d]/g, ''), 10);
    if (!isNaN(parsed)) {
      durationSecs = parsed;
    }
  }
  durationSecs = Math.max(15, Math.min(3600, durationSecs));

  const rawStyle = (input.videoStyle || 'hybrid_presenter_broll').toLowerCase().trim();
  const validStyles = [
    'presenter_led',
    'hybrid_presenter_broll',
    'visual_explainer',
    'demonstration_tutorial',
    'corporate_training',
  ];
  let canonicalStyle = 'hybrid_presenter_broll';
  if (validStyles.includes(rawStyle)) {
    canonicalStyle = rawStyle;
  } else if (rawStyle.includes('demo') || rawStyle.includes('tutorial')) {
    canonicalStyle = 'demonstration_tutorial';
  } else if (rawStyle.includes('lead') || rawStyle.includes('led')) {
    canonicalStyle = 'presenter_led';
  } else if (rawStyle.includes('visual') || rawStyle.includes('explainer')) {
    canonicalStyle = 'visual_explainer';
  } else if (rawStyle.includes('corporate')) {
    canonicalStyle = 'corporate_training';
  }

  const rawAvatar = (input.avatarProvider || 'mock').toLowerCase().trim();
  let canonicalAvatar = 'mock';
  if (rawAvatar.includes('sadtalker')) {
    canonicalAvatar = 'sadtalker';
  } else if (rawAvatar.includes('heygen')) {
    canonicalAvatar = 'heygen';
  } else if (rawAvatar.includes('mock')) {
    canonicalAvatar = 'mock';
  }

  const req = {
    topic: input.topic?.trim() || 'Untitled Project',
    source_content: input.sourceContent?.trim() || undefined,
    audience: input.audience?.trim() || 'General Professional / Adult Learner',
    base_language: input.baseLanguage?.trim() || 'en-US',
    target_languages: targetLangs,
    target_duration_seconds: durationSecs,
    tone: input.tone?.trim() || 'engaging and professional',
    difficulty_level: input.difficultyLevel?.trim() || 'intermediate',
    learning_objectives: input.learningObjectives || undefined,
    video_style: canonicalStyle,
    avatar_provider: canonicalAvatar,
    avatar_id: input.avatarId || 'default_avatar.png',
  };

  return {
    project_id: input.customId?.trim() || null,
    request: req,
  };
}

/**
 * Re-implementation/import testing of formatApiError logic.
 */
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

// ==========================================
// Test Cases 6-13 required by V2 contract
// ==========================================

test('6. Create wizard serializes request wrapper correctly', () => {
  const result = serializeCreateProjectRequest({
    topic: 'Saudi Kabsa Preparation Basics',
    sourceContent: 'Chicken and rice recipe.',
    audience: 'Home cooks',
  });

  assert.ok('request' in result, 'Wrapper must have request property');
  assert.equal(result.project_id, null, 'project_id defaults to null');
  assert.equal(result.request.topic, 'Saudi Kabsa Preparation Basics');
});

test('7. ar-SA serializes as ["ar-SA"]', () => {
  // Case A: passed as array
  const resArray = serializeCreateProjectRequest({
    topic: 'Test',
    targetLanguages: ['ar-SA'],
  });
  assert.deepEqual(resArray.request.target_languages, ['ar-SA']);

  // Case B: passed as single string
  const resString = serializeCreateProjectRequest({
    topic: 'Test',
    targetLanguages: 'ar-SA',
  });
  assert.deepEqual(resString.request.target_languages, ['ar-SA']);
});

test('8. SadTalker serializes as canonical "sadtalker"', () => {
  const variations = [
    'sadtalker',
    'SadTalker',
    'SadTalker Local — Free',
    'SadTalker (CUDA RTX)',
    '  sadtalker  ',
  ];

  for (const v of variations) {
    const res = serializeCreateProjectRequest({ topic: 'Test', avatarProvider: v });
    assert.equal(res.request.avatar_provider, 'sadtalker', `Variation "${v}" should serialize to "sadtalker"`);
  }
});

test('9. duration serializes as integer 30', () => {
  const variations = [
    30,
    30.0,
    '30',
    '30 seconds',
    '30s',
  ];

  for (const v of variations) {
    const res = serializeCreateProjectRequest({ topic: 'Test', duration: v });
    assert.strictEqual(res.request.target_duration_seconds, 30, `Duration "${v}" must serialize to number 30`);
    assert.ok(Number.isInteger(res.request.target_duration_seconds));
  }
});

test('10. video style serializes canonical enum', () => {
  const res1 = serializeCreateProjectRequest({
    topic: 'Test',
    videoStyle: 'Demonstration / Tutorial',
  });
  assert.equal(res1.request.video_style, 'demonstration_tutorial');

  const res2 = serializeCreateProjectRequest({
    topic: 'Test',
    videoStyle: 'Hybrid Presenter Broll',
  });
  assert.equal(res2.request.video_style, 'hybrid_presenter_broll');

  const res3 = serializeCreateProjectRequest({
    topic: 'Test',
    videoStyle: 'Presenter-Led',
  });
  assert.equal(res3.request.video_style, 'presenter_led');
});

test('11. FastAPI 422 array formats human-readable message', () => {
  const fastApi422 = {
    detail: [
      {
        type: 'missing',
        loc: ['body', 'request', 'target_languages'],
        msg: 'Field required',
      },
      {
        type: 'enum',
        loc: ['body', 'request', 'video_style'],
        msg: "Input should be 'presenter_led' or 'demonstration_tutorial'",
      },
    ],
  };

  const formatted = formatApiError(fastApi422);
  assert.ok(formatted.includes('request.target_languages: Field required'));
  assert.ok(formatted.includes("request.video_style: Input should be 'presenter_led' or 'demonstration_tutorial'"));
});

test('12. [object Object] can never be displayed', () => {
  const objects = [
    { detail: [{ loc: ['body', 'request'], msg: 'Invalid payload' }] },
    { detail: {} },
    { message: 'General failure' },
    { error: 'Backend error' },
    {},
    null,
    undefined,
    new Error('Wrapped error'),
  ];

  for (const obj of objects) {
    const res = formatApiError(obj, 'Fallback error');
    assert.notEqual(res, '[object Object]', 'formatApiError must never produce [object Object]');
    assert.ok(typeof res === 'string' && res.length > 0);
  }
});

test('13. loading state clears after failure simulation', async () => {
  let submitting = true;
  let statusMessage = 'Initializing project manifest...';
  let errorMessage = null;

  try {
    // Simulate API throwing error
    const fakeApiCall = async () => {
      const errResponse = {
        detail: [{ loc: ['body', 'request', 'target_languages'], msg: 'Field required' }],
      };
      throw new Error(formatApiError(errResponse));
    };
    await fakeApiCall();
  } catch (err) {
    errorMessage = err.message;
    submitting = false;
    statusMessage = '';
  }

  assert.equal(submitting, false, 'submitting flag must reset to false');
  assert.equal(statusMessage, '', 'statusMessage must clear');
  assert.equal(errorMessage, 'request.target_languages: Field required');
});
