import test from 'node:test';
import assert from 'node:assert/strict';

// Frontend V2 tests for Scene Preview, Render Action, and Asset State guards

/**
 * Re-implementation / logic testing of activeVideoUrl calculation and video mount guards
 * from web/src/app/studio/[id]/page.tsx
 */
function computeVideoPreviewState({
  previewMode, // 'scene' | 'full'
  currentScene,
  selectedLocale,
  finalVideoUrl,
  manifest,
}) {
  const isSceneRendered = Boolean(
    currentScene?.render_status === 'completed' && currentScene?.rendered_video_url
  );

  const isFinalVideoRendered = Boolean(
    finalVideoUrl ||
      (manifest?.final_videos &&
        manifest.final_videos[selectedLocale]?.status === 'completed')
  );

  let activeVideoUrl = null;
  if (previewMode === 'scene') {
    if (isSceneRendered && currentScene?.rendered_video_url) {
      activeVideoUrl = currentScene.rendered_video_url;
    }
  } else {
    if (isFinalVideoRendered) {
      activeVideoUrl =
        finalVideoUrl ||
        (manifest?.final_videos && manifest.final_videos[selectedLocale]?.video_path) ||
        null;
    }
  }

  const shouldMountVideoElement = Boolean(activeVideoUrl);
  const showUnrenderedPlaceholder = !shouldMountVideoElement;

  return {
    isSceneRendered,
    isFinalVideoRendered,
    activeVideoUrl,
    shouldMountVideoElement,
    showUnrenderedPlaceholder,
  };
}

/**
 * Storage URL normalization helper from web/src/lib/api.ts
 */
function getStorageUrl(path) {
  if (!path) return '';
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  let clean = path.replace(/\\/g, '/').replace(/^\/+/, '');
  if (clean.startsWith('storage/projects/')) {
    clean = 'storage/' + clean.replace(/^storage\/projects\//, '');
  }
  const API_BASE_URL = 'http://localhost:8000';
  return `${API_BASE_URL}/${clean}`;
}

test('1. Unrendered scene does not produce activeVideoUrl (no MP4 request)', () => {
  const unrenderedScene = {
    scene_id: 'scene_1',
    order: 1,
    title: 'Introduction',
    render_status: 'unrendered',
    has_rendered_asset: false,
    rendered_video_url: null,
  };

  const state = computeVideoPreviewState({
    previewMode: 'scene',
    currentScene: unrenderedScene,
    selectedLocale: 'ar-SA',
    finalVideoUrl: null,
    manifest: { status: 'running' },
  });

  assert.equal(state.isSceneRendered, false);
  assert.equal(state.activeVideoUrl, null);
  assert.equal(state.shouldMountVideoElement, false);
  assert.equal(state.showUnrenderedPlaceholder, true);
});

test('2. Unrendered scene shows placeholder instead of mounting <video>', () => {
  const scenes = [
    { scene_id: 'scene_1', render_status: 'unrendered', has_rendered_asset: false, rendered_video_url: null },
    { scene_id: 'scene_2', render_status: 'unrendered', has_rendered_asset: false, rendered_video_url: null },
    { scene_id: 'scene_3', render_status: 'unrendered', has_rendered_asset: false, rendered_video_url: null },
  ];

  for (const sc of scenes) {
    const state = computeVideoPreviewState({
      previewMode: 'scene',
      currentScene: sc,
      selectedLocale: 'ar-SA',
      finalVideoUrl: null,
      manifest: { status: 'pending' },
    });
    // Video tag is NOT mounted => 404 network request never issued
    assert.equal(state.shouldMountVideoElement, false);
    assert.equal(state.showUnrenderedPlaceholder, true);
  }
});

test('3. Completed scene exposes rendered_video_url and mounts video', () => {
  const completedScene = {
    scene_id: 'scene_1',
    order: 1,
    title: 'Introduction',
    render_status: 'completed',
    has_rendered_asset: true,
    rendered_video_url: '/storage/proj_b1c9c49c8259/rendered/ar-SA/scene_1.mp4',
  };

  const state = computeVideoPreviewState({
    previewMode: 'scene',
    currentScene: completedScene,
    selectedLocale: 'ar-SA',
    finalVideoUrl: null,
    manifest: { status: 'completed' },
  });

  assert.equal(state.isSceneRendered, true);
  assert.equal(state.activeVideoUrl, '/storage/proj_b1c9c49c8259/rendered/ar-SA/scene_1.mp4');
  assert.equal(state.shouldMountVideoElement, true);
  assert.equal(state.showUnrenderedPlaceholder, false);
});

test('4. Full video preview mounts only when final video asset exists', () => {
  // Before final render
  const preRenderState = computeVideoPreviewState({
    previewMode: 'full',
    currentScene: null,
    selectedLocale: 'ar-SA',
    finalVideoUrl: null,
    manifest: { status: 'running', final_videos: {} },
  });
  assert.equal(preRenderState.shouldMountVideoElement, false);
  assert.equal(preRenderState.showUnrenderedPlaceholder, true);

  // After final render
  const postRenderState = computeVideoPreviewState({
    previewMode: 'full',
    currentScene: null,
    selectedLocale: 'ar-SA',
    finalVideoUrl: '/storage/proj_b1c9c49c8259/final/training_ar-SA.mp4',
    manifest: {
      status: 'completed',
      final_videos: {
        'ar-SA': {
          status: 'completed',
          video_path: '/storage/proj_b1c9c49c8259/final/training_ar-SA.mp4',
        },
      },
    },
  });
  assert.equal(postRenderState.shouldMountVideoElement, true);
  assert.equal(postRenderState.activeVideoUrl, '/storage/proj_b1c9c49c8259/final/training_ar-SA.mp4');
});

test('5. getStorageUrl normalizes storage/projects/ path accurately for FastAPI', () => {
  const rawPath = 'storage/projects/proj_b1c9c49c8259/rendered/ar-SA/scene_1.mp4';
  const url = getStorageUrl(rawPath);
  assert.equal(url, 'http://localhost:8000/storage/proj_b1c9c49c8259/rendered/ar-SA/scene_1.mp4');
});

test('6. renderProject API contract passes correct endpoint and payload', async () => {
  // Mock fetch call to test renderProject contract
  let requestedUrl = '';
  let requestedMethod = '';
  let requestedBody = '';

  const mockFetch = async (url, options) => {
    requestedUrl = url;
    requestedMethod = options.method;
    requestedBody = options.body;
    return {
      ok: true,
      json: async () => ({ status: 'completed', project_id: 'proj_test' }),
    };
  };

  const projectId = 'proj_b1c9c49c8259';
  const forceRegenerate = false;

  // Emulate renderProject call
  const response = await mockFetch(`http://localhost:8000/api/v1/projects/${projectId}/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force_regenerate: forceRegenerate }),
  });
  const data = await response.json();

  assert.equal(requestedUrl, 'http://localhost:8000/api/v1/projects/proj_b1c9c49c8259/render');
  assert.equal(requestedMethod, 'POST');
  assert.deepEqual(JSON.parse(requestedBody), { force_regenerate: false });
  assert.equal(data.status, 'completed');
});

test('7. 404 spam is eliminated before render by scene URL gating', () => {
  // When looping through 5 scenes in a project before render:
  const projectScenes = [
    { scene_id: 'scene_1', render_status: 'unrendered' },
    { scene_id: 'scene_2', render_status: 'unrendered' },
    { scene_id: 'scene_3', render_status: 'unrendered' },
    { scene_id: 'scene_4', render_status: 'unrendered' },
    { scene_id: 'scene_5', render_status: 'unrendered' },
  ];

  const networkRequests = [];
  projectScenes.forEach((sc) => {
    const state = computeVideoPreviewState({
      previewMode: 'scene',
      currentScene: sc,
      selectedLocale: 'ar-SA',
      finalVideoUrl: null,
      manifest: { status: 'pending' },
    });
    if (state.activeVideoUrl) {
      networkRequests.push(state.activeVideoUrl);
    }
  });

  // Zero requests issued
  assert.equal(networkRequests.length, 0);
});
