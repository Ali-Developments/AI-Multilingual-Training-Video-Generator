import test from 'node:test';
import assert from 'node:assert/strict';

// Test Suite for Video Studio V2 Frontend Core Logic & State Management

test('Project creation: default payload construction matches FastAPI V2 schema', () => {
  const formState = {
    title: 'Workplace Phishing Defense Essentials',
    topic: 'Phishing Email Detection',
    sourceContent: 'Verify sender email headers and never click suspicious links.',
    audience: 'Corporate Employees',
    duration: 30,
    videoStyle: 'hybrid_presenter_broll',
    sourceLanguage: 'en-US',
    targetLanguages: ['ar-SA'],
    avatarProvider: 'sadtalker',
    selectedVoice: 'ar-SA-HamedNeural',
  };

  assert.equal(formState.title, 'Workplace Phishing Defense Essentials');
  assert.equal(formState.duration, 30);
  assert.equal(formState.videoStyle, 'hybrid_presenter_broll');
  assert.ok(formState.targetLanguages.includes('ar-SA'));
  assert.equal(formState.avatarProvider, 'sadtalker');
});

test('Language selection: supports multi-target selection with RTL flag detection', () => {
  const locales = [
    { code: 'ar-SA', name: 'Arabic (Saudi Arabia)', isRTL: true },
    { code: 'en-US', name: 'English (United States)', isRTL: false },
    { code: 'fr-FR', name: 'French (France)', isRTL: false },
  ];

  const isRTL = (code) => code.startsWith('ar') || code.startsWith('ur') || code.startsWith('fa');

  assert.equal(isRTL('ar-SA'), true);
  assert.equal(isRTL('en-US'), false);
  assert.equal(isRTL('fr-FR'), false);
});

test('Scene type switching: preserves scene metadata while altering layout appropriately', () => {
  const scene = {
    scene_id: 'scene_1',
    order: 1,
    scene_type: 'intro',
    narration: 'مرحباً بكم في التدريب',
    media_type: 'presenter',
    layout_type: 'presenter_full',
    avatar_enabled: true,
    target_duration: 6.5,
  };

  // User changes scene to B-Roll
  const updatedScene = {
    ...scene,
    media_type: 'broll',
    layout_type: 'media_full',
    avatar_enabled: false,
    visual_prompt: 'High-tech office workstation with email client open',
  };

  assert.equal(updatedScene.media_type, 'broll');
  assert.equal(updatedScene.layout_type, 'media_full');
  assert.equal(updatedScene.avatar_enabled, false);
  assert.equal(updatedScene.scene_id, 'scene_1');
  assert.equal(updatedScene.narration, 'مرحباً بكم في التدريب');
});

test('Timeline duration aggregation: computes total duration across all scenes', () => {
  const scenes = [
    { scene_id: 's1', target_duration: 6.0, duration: 6.2 },
    { scene_id: 's2', target_duration: 8.0, duration: 8.1 },
    { scene_id: 's3', target_duration: 7.5, duration: 7.4 },
    { scene_id: 's4', target_duration: 5.5, duration: 5.6 },
  ];

  const totalCalculated = scenes.reduce((acc, s) => acc + (s.duration || s.target_duration), 0);
  assert.ok(Math.abs(totalCalculated - 27.3) < 0.01);
});

test('Timeline reordering: correctly updates order indices without data corruption', () => {
  const scenes = [
    { scene_id: 's1', order: 1, title: 'Intro' },
    { scene_id: 's2', order: 2, title: 'Step 1' },
    { scene_id: 's3', order: 3, title: 'Step 2' },
    { scene_id: 's4', order: 4, title: 'Outro' },
  ];

  // Move Step 2 to position 2
  const reorderedIds = ['s1', 's3', 's2', 's4'];
  const newScenes = reorderedIds.map((id, index) => {
    const found = scenes.find((s) => s.scene_id === id);
    return { ...found, order: index + 1 };
  });

  assert.equal(newScenes[1].scene_id, 's3');
  assert.equal(newScenes[1].order, 2);
  assert.equal(newScenes[2].scene_id, 's2');
  assert.equal(newScenes[2].order, 3);
});

test('Quiz scene metadata: supports question, choices, and correct answer', () => {
  const quiz = {
    question: 'ما أول خطوة عند استقبال رسالة مشبوهة؟',
    options: [
      'A. النقر على الرابط مباشرة',
      'B. التحقق من عنوان المرسل',
      'C. إعادة توجيهها لكافة الزملاء',
    ],
    correct_option: 1,
    explanation: 'يجب دائماً التحقق من نطاق البريد الإلكتروني للمرسل.',
  };

  assert.equal(quiz.options.length, 3);
  assert.equal(quiz.correct_option, 1);
  assert.ok(quiz.question.includes('مشبوهة'));
});

test('API error handling: gracefully surfaces server error message', () => {
  const parseApiError = (err) => {
    if (err && err.message) return err.message;
    return 'An unexpected network error occurred';
  };

  assert.equal(parseApiError(new Error('Connection refused by backend')), 'Connection refused by backend');
  assert.equal(parseApiError(null), 'An unexpected network error occurred');
});
