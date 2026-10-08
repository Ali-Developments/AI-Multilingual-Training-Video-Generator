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

export interface TrainingVideoRequest {
  topic: string;
  source_content?: string;
  audience?: string;
  base_language?: string;
  target_languages?: string[];
  target_duration_seconds?: number;
  video_style?: VideoStyle;
  avatar_provider?: string;
  avatar_id?: string;
  branding?: BrandingConfig;
}

export interface ProjectSummary {
  project_id: string;
  title: string;
  source_language: string;
  target_languages: string[];
  duration_seconds: number;
  status: string;
  avatar_provider: string;
  thumbnail_path?: string;
  created_at: string;
  updated_at: string;
}

export interface FinalVideoAsset {
  locale: string;
  video_path: string;
  duration_seconds: number;
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
