import {
  ProjectManifest,
  ProjectSummary,
  CreateProjectRequest,
  TrainingVideoRequest,
  SceneDraft,
  UploadedMediaItem,
  ProviderStatus,
  VideoStyle,
} from '@/types';

const API_BASE =
  typeof process !== 'undefined' && process.env?.NEXT_PUBLIC_API_URL
    ? `${process.env.NEXT_PUBLIC_API_URL.replace(/\/$/, '')}/api/v1`
    : '/api/v1';

/**
 * Formats API errors (including FastAPI 422 validation detail arrays) into human-readable messages.
 * Guarantees [object Object] will NEVER be returned or displayed.
 */
export function formatApiError(errData: any, fallback = 'Operation failed'): string {
  if (!errData) return fallback;
  if (typeof errData === 'string') return errData;

  // FastAPI detail can be string or array of error objects
  if (typeof errData.detail === 'string') {
    return errData.detail;
  }

  if (Array.isArray(errData.detail)) {
    const formatted = errData.detail
      .map((item: any) => {
        if (!item) return '';
        if (typeof item === 'string') return item;
        const loc = Array.isArray(item.loc)
          ? item.loc.filter((part: any) => part !== 'body').join('.')
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

/**
 * Safely extracts error details from an HTTP response, supporting both JSON error envelopes
 * and non-JSON plaintext / HTML proxy or server error messages.
 */
export async function parseResponseError(res: Response, fallback = 'Operation failed'): Promise<string> {
  let errData: any = null;
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

export async function fetchProjects(): Promise<ProjectManifest[]> {
  const res = await fetch(`${API_BASE}/projects`);
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to fetch projects'));
  }
  return res.json();
}

export async function fetchProjectSummaries(): Promise<ProjectSummary[]> {
  const res = await fetch(`${API_BASE}/projects/summaries`);
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to fetch project summaries'));
  }
  return res.json();
}

export async function fetchProject(projectId: string): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`);
  if (!res.ok) {
    throw new Error(await parseResponseError(res, `Project ${projectId} not found`));
  }
  return res.json();
}

export async function createProject(
  payload: CreateProjectRequest | TrainingVideoRequest,
  customId?: string
): Promise<ProjectManifest> {
  let bodyPayload: CreateProjectRequest;
  if ('request' in payload && payload.request) {
    bodyPayload = {
      project_id: payload.project_id ?? customId ?? null,
      request: payload.request,
    };
  } else {
    bodyPayload = {
      project_id: customId ?? null,
      request: payload as TrainingVideoRequest,
    };
  }

  const res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(bodyPayload),
  });

  if (!res.ok) {
    throw new Error(await parseResponseError(res, `Project creation failed`));
  }

  return res.json();
}

export async function updateProject(
  projectId: string,
  payload: Partial<TrainingVideoRequest>
): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to update project'));
  }
  return res.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to delete project'));
  }
}

export async function duplicateProject(projectId: string): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/duplicate`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to duplicate project'));
  }
  return res.json();
}

export async function fetchScenes(
  projectId: string,
  locale?: string
): Promise<SceneDraft[]> {
  const url = locale
    ? `${API_BASE}/projects/${projectId}/scenes?locale=${encodeURIComponent(locale)}`
    : `${API_BASE}/projects/${projectId}/scenes`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to fetch scenes'));
  }
  return res.json();
}

export async function updateScene(
  projectId: string,
  sceneId: string,
  payload: Partial<SceneDraft>,
  locale?: string
): Promise<{ message: string; scene: SceneDraft }> {
  const url = locale
    ? `${API_BASE}/projects/${projectId}/scenes/${sceneId}?locale=${encodeURIComponent(locale)}`
    : `${API_BASE}/projects/${projectId}/scenes/${sceneId}`;
  const res = await fetch(url, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to update scene'));
  }
  return res.json();
}

export async function reorderScenes(
  projectId: string,
  sceneIds: string[]
): Promise<{ message: string; scene_ids: string[] }> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/scenes/reorder`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scene_ids: sceneIds, scene_order: sceneIds }),
  });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to reorder scenes'));
  }
  return res.json();
}

export async function generateScript(
  projectId: string,
  forceRegenerate: boolean = false
): Promise<ProjectManifest> {
  const url = `${API_BASE}/projects/${projectId}/generate-script?force_regenerate=${forceRegenerate}`;
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to generate script'));
  }
  return res.json();
}

export async function prepareStudio(
  projectId: string,
  videoStyle?: VideoStyle,
  forceRegenerate: boolean = false
): Promise<ProjectManifest> {
  const params = new URLSearchParams();
  if (videoStyle) params.append('video_style', videoStyle);
  if (forceRegenerate) params.append('force_regenerate', 'true');
  const query = params.toString();
  const url = query ? `${API_BASE}/projects/${projectId}/prepare-studio?${query}` : `${API_BASE}/projects/${projectId}/prepare-studio`;
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to prepare studio project'));
  }
  return res.json();
}

export async function planStoryboard(
  projectId: string,
  videoStyle?: VideoStyle
): Promise<ProjectManifest> {
  const url = videoStyle
    ? `${API_BASE}/projects/${projectId}/plan-storyboard?video_style=${encodeURIComponent(videoStyle)}`
    : `${API_BASE}/projects/${projectId}/plan-storyboard`;
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to plan storyboard'));
  }
  return res.json();
}

export async function runPipeline(
  projectId: string,
  forceRegenerate: boolean = false
): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force_regenerate: forceRegenerate }),
  });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Pipeline execution failed'));
  }
  return res.json();
}

export async function renderProject(
  projectId: string,
  forceRegenerate: boolean = false
): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ force_regenerate: forceRegenerate }),
  });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Rendering execution failed'));
  }
  return res.json();
}

export async function uploadMedia(
  projectId: string,
  file: File
): Promise<UploadedMediaItem> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/projects/${projectId}/media`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to upload media file'));
  }
  return res.json();
}

export async function fetchProjectMedia(
  projectId: string
): Promise<UploadedMediaItem[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/media`);
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to fetch project media'));
  }
  return res.json();
}

export async function fetchProvidersStatus(): Promise<ProviderStatus> {
  const res = await fetch(`${API_BASE}/providers/status`);
  if (!res.ok) {
    throw new Error(await parseResponseError(res, 'Failed to fetch provider readiness'));
  }
  return res.json();
}

/**
 * Convert backend absolute/relative file path into a web-accessible static storage URL.
 * e.g. D:\...\storage\proj_xxx\final_videos\ar-SA.mp4 -> /storage/proj_xxx/final_videos/ar-SA.mp4
 */
export function getStorageUrl(filePath?: string | null): string {
  if (!filePath) return '';
  if (filePath.startsWith('http://') || filePath.startsWith('https://')) return filePath;
  const normalized = filePath.replace(/\\/g, '/');

  // Strip storage/projects/ prefix because FastAPI mounts storage/projects directly at /storage
  if (normalized.includes('/storage/projects/')) {
    return '/storage/' + normalized.split('/storage/projects/')[1];
  }
  if (normalized.startsWith('storage/projects/')) {
    return '/storage/' + normalized.substring('storage/projects/'.length);
  }
  if (normalized.startsWith('/storage/projects/')) {
    return '/storage/' + normalized.substring('/storage/projects/'.length);
  }

  const storageIndex = normalized.indexOf('/storage/');
  if (storageIndex !== -1) {
    return normalized.substring(storageIndex);
  }
  if (normalized.startsWith('storage/')) {
    return `/${normalized}`;
  }
  return `/storage/${normalized.split('/').pop()}`;
}
