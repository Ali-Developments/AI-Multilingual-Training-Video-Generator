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

const API_BASE = '/api/v1';

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

export async function fetchProjects(): Promise<ProjectManifest[]> {
  const res = await fetch(`${API_BASE}/projects`);
  if (!res.ok) {
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to fetch projects'));
  }
  return res.json();
}

export async function fetchProjectSummaries(): Promise<ProjectSummary[]> {
  const res = await fetch(`${API_BASE}/projects/summaries`);
  if (!res.ok) {
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to fetch project summaries'));
  }
  return res.json();
}

export async function fetchProject(projectId: string): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`);
  if (!res.ok) {
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, `Project ${projectId} not found`));
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
    const errData = await res.json().catch(() => null);
    const msg = formatApiError(errData, `Project creation failed (HTTP ${res.status})`);
    throw new Error(msg);
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
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to update project'));
  }
  return res.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to delete project'));
  }
}

export async function duplicateProject(projectId: string): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/duplicate`, {
    method: 'POST',
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to duplicate project'));
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
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to fetch scenes'));
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
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to update scene'));
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
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to reorder scenes'));
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
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to plan storyboard'));
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
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Pipeline execution failed'));
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
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to upload media file'));
  }
  return res.json();
}

export async function fetchProjectMedia(
  projectId: string
): Promise<UploadedMediaItem[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/media`);
  if (!res.ok) {
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to fetch project media'));
  }
  return res.json();
}

export async function fetchProvidersStatus(): Promise<ProviderStatus> {
  const res = await fetch(`${API_BASE}/providers/status`);
  if (!res.ok) {
    const errData = await res.json().catch(() => null);
    throw new Error(formatApiError(errData, 'Failed to fetch provider readiness'));
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
  const storageIndex = normalized.indexOf('/storage/');
  if (storageIndex !== -1) {
    return normalized.substring(storageIndex);
  }
  if (normalized.startsWith('storage/')) {
    return `/${normalized}`;
  }
  return `/storage/${normalized.split('/').pop()}`;
}
