/**
 * TypeScript types for AI Training Video Studio V2.
 * Synchronized with FastAPI schemas.
 */

export type SceneMediaType =
  | 'presenter'
  | 'broll'
  | 'uploaded_video'
  | 'uploaded_image'
  | 'motion_visual'
  | 'diagram'
  | 'title'
  | 'quiz'
  | 'outro';

export type SceneLayoutType =
  | 'presenter_full'
  | 'presenter_split'
  | 'media_full'
  | 'media_with_overlay'
  | 'presenter_overlay'
  | 'title_card'
  | 'quiz_card';

export type VideoStyle =
  | 'presenter_led'
  | 'hybrid_presenter_broll'
  | 'visual_explainer'
  | 'demonstration_tutorial'
  | 'corporate_training';

export interface QuizData {
  question: string;
  options: string[];
  correct_index: number;
  explanation?: string;
}

export interface BrandingConfig {
  logo_path?: string;
  primary_color?: string;
  secondary_color?: string;
  font_family?: string;
  intro_title?: string;
  outro_cta?: string;
}

export interface SceneDraft {
  scene_id: string;
  order: number;
  title: string;
  narration: string;
  purpose?: string;
  scene_type?: string;
  media_type?: SceneMediaType;
  layout_type?: SceneLayoutType;
  visual_prompt?: string;
  media_search_terms?: string[];
  avatar_enabled?: boolean;
  presenter_position?: 'left' | 'right' | 'center';
  on_screen_text?: string;
  transition?: string;
  estimated_duration_seconds?: number;
  target_duration?: number;
  media_asset_path?: string;
  quiz_data?: QuizData;
  render_status?: 'completed' | 'rendering' | 'failed' | 'unrendered' | 'pending' | null;
  rendered_video_url?: string | null;
  has_rendered_asset?: boolean;
}

export interface LocalizedScene extends SceneDraft {
  locale?: string;
  measured_duration_seconds?: number;
}

export interface FinalScript {
  title: string;
  language: string;
  audience: string;
  target_duration_seconds: number;
  total_estimated_duration_seconds: number;
  opening_hook: string;
  closing_summary: string;
  scenes: SceneDraft[];
}

export interface LocalizedScript {
  locale: string;
  title: string;
  scenes: LocalizedScene[];
  total_duration_seconds?: number;
}

export interface CreateProjectRequest {
  project_id?: string | null;
  request: TrainingVideoRequest;
}

export interface TrainingVideoRequest {
  topic?: string | null;
  source_content?: string | null;
  audience?: string;
  base_language?: string;
  target_languages?: string[];
  target_duration_seconds?: number;
  tone?: string;
  difficulty_level?: string | null;
  learning_objectives?: string[] | null;
  locale?: string | null;
  avatar_provider?: string;
  avatar_id?: string;
  ack_paid_credits?: boolean;
  video_style?: VideoStyle;
  branding?: BrandingConfig | null;
}

export interface ProjectSummary {
  project_id: string;
  topic: string;
  title: string;
  base_language: string;
  source_language: string;
  target_languages: string[];
  target_duration_seconds: number;
  duration_seconds: number;
  status: string;
  avatar_provider: string;
  video_style?: string;
  created_at: string;
  updated_at: string;
  scenes_count?: number;
  completed_locales?: string[];
  thumbnail_url?: string | null;
  thumbnail_path?: string | null;
  is_legacy?: boolean;
  migration_required?: boolean;
}

/**
 * Canonical serializer for creating a new video automation project.
 * Enforces strict typing, clean enums, integer duration, and wrapper structure.
 */
export function serializeCreateProjectRequest(input: {
  topic: string;
  sourceContent?: string;
  audience?: string;
  baseLanguage?: string;
  targetLanguages?: string[] | string;
  duration?: number | string;
  videoStyle?: string;
  avatarProvider?: string;
  avatarId?: string;
  tone?: string;
  difficultyLevel?: string;
  learningObjectives?: string[];
  customId?: string | null;
}): CreateProjectRequest {
  // 1. Sanitize target languages to string array
  let targetLangs: string[] = ['en-US'];
  if (Array.isArray(input.targetLanguages)) {
    targetLangs = input.targetLanguages.filter((l) => typeof l === 'string' && l.trim().length > 0);
  } else if (typeof input.targetLanguages === 'string' && input.targetLanguages.trim().length > 0) {
    targetLangs = [input.targetLanguages.trim()];
  }
  if (targetLangs.length === 0) {
    targetLangs = [input.baseLanguage?.trim() || 'en-US'];
  }

  // 2. Sanitize duration to valid integer between 15 and 3600
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

  // 3. Sanitize video_style to canonical enum
  const rawStyle = (input.videoStyle || 'hybrid_presenter_broll').toLowerCase().trim();
  const validStyles: VideoStyle[] = [
    'presenter_led',
    'hybrid_presenter_broll',
    'visual_explainer',
    'demonstration_tutorial',
    'corporate_training',
  ];
  let canonicalStyle: VideoStyle = 'hybrid_presenter_broll';
  if (validStyles.includes(rawStyle as VideoStyle)) {
    canonicalStyle = rawStyle as VideoStyle;
  } else if (rawStyle.includes('demo') || rawStyle.includes('tutorial')) {
    canonicalStyle = 'demonstration_tutorial';
  } else if (rawStyle.includes('lead') || rawStyle.includes('led')) {
    canonicalStyle = 'presenter_led';
  } else if (rawStyle.includes('visual') || rawStyle.includes('explainer')) {
    canonicalStyle = 'visual_explainer';
  } else if (rawStyle.includes('corporate')) {
    canonicalStyle = 'corporate_training';
  }

  // 4. Sanitize avatar_provider to canonical enum ('sadtalker', 'heygen', 'mock')
  const rawAvatar = (input.avatarProvider || 'mock').toLowerCase().trim();
  let canonicalAvatar = 'mock';
  if (rawAvatar.includes('sadtalker')) {
    canonicalAvatar = 'sadtalker';
  } else if (rawAvatar.includes('heygen')) {
    canonicalAvatar = 'heygen';
  } else if (rawAvatar.includes('mock')) {
    canonicalAvatar = 'mock';
  }

  const req: TrainingVideoRequest = {
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

export interface FinalVideoAsset {
  locale: string;
  video_path: string;
  duration_seconds?: number;
  total_duration_seconds?: number;
  status: string;
}

export interface ProjectManifest {
  project_id: string;
  created_at: string;
  updated_at: string;
  status: string;
  avatar_provider: string;
  source_request: TrainingVideoRequest;
  script_status: string;
  localization_status: string;
  audio_status: string;
  avatar_status: string;
  visual_status: string;
  subtitle_status: string;
  composition_status: string;
  final_script?: FinalScript;
  localization_bundle?: {
    localized_scripts: Record<string, LocalizedScript>;
  };
  audio_tracks?: Record<string, { status: string; total_duration_seconds: number }>;
  final_videos?: Record<string, FinalVideoAsset>;
  errors?: string[];
}

export interface UploadedMediaItem {
  media_id: string;
  project_id: string;
  filename: string;
  file_path: string;
  media_type: 'video' | 'image';
  file_size_bytes: number;
}

export interface ProviderStatus {
  sadtalker: {
    name: string;
    available: boolean;
    gpu_available: boolean;
    gpu_name: string;
    ready: boolean;
  };
  heygen: {
    name: string;
    available: boolean;
    ready: boolean;
  };
  groq: {
    name: string;
    available: boolean;
    ready: boolean;
  };
  edge_tts: {
    name: string;
    available: boolean;
    ready: boolean;
  };
  ffmpeg: {
    name: string;
    available: boolean;
    ready: boolean;
  };
}
