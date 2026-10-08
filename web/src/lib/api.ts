import {
  ProjectManifest,
  ProjectSummary,
  TrainingVideoRequest,
  SceneDraft,
  UploadedMediaItem,
  ProviderStatus,
  VideoStyle,
} from '@/types';

const API_BASE = '/api/v1';

export async function fetchProjects(): Promise<ProjectManifest[]> {
  const res = await fetch(`${API_BASE}/projects`);
  if (!res.ok) throw new Error('Failed to fetch projects');
  return res.json();
}

export async function fetchProjectSummaries(): Promise<ProjectSummary[]> {
  const res = await fetch(`${API_BASE}/projects/summaries`);
  if (!res.ok) throw new Error('Failed to fetch project summaries');
  return res.json();
}

export async function fetchProject(projectId: string): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`);
  if (!res.ok) throw new Error(`Project ${projectId} not found`);
  return res.json();
}

export async function createProject(
  request: TrainingVideoRequest,
  customId?: string
): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: customId, request }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to create project');
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
  if (!res.ok) throw new Error('Failed to update project');
  return res.json();
}

export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/${projectId}`, {
    method: 'DELETE',
  });
  if (!res.ok) throw new Error('Failed to delete project');
}

export async function duplicateProject(projectId: string): Promise<ProjectManifest> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/duplicate`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to duplicate project');
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
  if (!res.ok) throw new Error('Failed to fetch scenes');
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
  if (!res.ok) throw new Error('Failed to update scene');
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
  if (!res.ok) throw new Error('Failed to reorder scenes');
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
  if (!res.ok) throw new Error('Failed to plan storyboard');
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
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Pipeline execution failed');
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
  if (!res.ok) throw new Error('Failed to upload media file');
  return res.json();
}

export async function fetchProjectMedia(
  projectId: string
): Promise<UploadedMediaItem[]> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/media`);
  if (!res.ok) throw new Error('Failed to fetch project media');
  return res.json();
}

export async function fetchProvidersStatus(): Promise<ProviderStatus> {
  const res = await fetch(`${API_BASE}/providers/status`);
  if (!res.ok) throw new Error('Failed to fetch provider readiness');
  return res.json();
}

/**
 * Convert backend absolute/relative file path into a web-accessible static storage URL.
 * e.g. D:\...\storage\proj_xxx\final_videos\ar-SA.mp4 -> /storage/proj_xxx/final_videos/ar-SA.mp4
 */
export function getStorageUrl(filePath?: string): string {
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
