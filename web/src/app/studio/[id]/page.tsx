'use client';

import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  Play,
  Pause,
  RotateCcw,
  Sparkles,
  User,
  Film,
  ChevronUp,
  ChevronDown,
  Download,
  Upload,
  Globe2,
  RefreshCw,
  Wand2,
  Save,
} from 'lucide-react';
import {
  fetchProject,
  fetchScenes,
  updateScene,
  reorderScenes,
  planStoryboard,
  runPipeline,
  getStorageUrl,
  fetchProjectMedia,
  uploadMedia,
} from '@/lib/api';
import {
  ProjectManifest,
  SceneDraft,
  SceneMediaType,
  SceneLayoutType,
  UploadedMediaItem,
} from '@/types';

export default function SceneStudioPage() {
  const params = useParams();
  const projectId = params?.id as string;

  const [manifest, setManifest] = useState<ProjectManifest | null>(null);
  const [scenes, setScenes] = useState<SceneDraft[]>([]);
  const [mediaList, setMediaList] = useState<UploadedMediaItem[]>([]);
  const [selectedSceneIndex, setSelectedSceneIndex] = useState(0);
  const [selectedLocale, setSelectedLocale] = useState<string>('ar-SA');
  const [loading, setLoading] = useState(true);
  const [savingScene, setSavingScene] = useState(false);
  const [rendering, setRendering] = useState(false);

  // Inspector form state
  const [activeScene, setActiveScene] = useState<SceneDraft | null>(null);

  // Player state
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [previewMode, setPreviewMode] = useState<'scene' | 'full'>('scene');

  const loadProjectData = useCallback(async () => {
    try {
      setLoading(true);
      const proj = await fetchProject(projectId);
      setManifest(proj);

      const locales = proj.source_request.target_languages || [proj.source_request.base_language || 'en-US'];
      const defaultLoc = locales.includes('ar-SA') ? 'ar-SA' : locales[0];
      setSelectedLocale(defaultLoc);

      const scList = await fetchScenes(projectId, defaultLoc);
      setScenes(scList);
      if (scList.length > 0) {
        setActiveScene({ ...scList[0] });
      }

      const mediaItems = await fetchProjectMedia(projectId).catch(() => []);
      setMediaList(mediaItems);
    } catch (err) {
      console.error('Failed to load project:', err);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (projectId) {
      loadProjectData();
    }
  }, [projectId, loadProjectData]);

  // Synchronize active scene when selection changes
  useEffect(() => {
    if (scenes[selectedSceneIndex]) {
      setActiveScene({ ...scenes[selectedSceneIndex] });
    }
  }, [selectedSceneIndex, scenes]);

  const handleLocaleChange = async (newLoc: string) => {
    setSelectedLocale(newLoc);
    try {
      const scList = await fetchScenes(projectId, newLoc);
      setScenes(scList);
      if (scList.length > 0) {
        const nextIdx = Math.min(selectedSceneIndex, scList.length - 1);
        setActiveScene({ ...scList[nextIdx] });
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleSaveScene = async () => {
    if (!activeScene) return;
    try {
      setSavingScene(true);
      await updateScene(projectId, activeScene.scene_id, activeScene, selectedLocale);
      // Reload scenes
      const updated = await fetchScenes(projectId, selectedLocale);
      setScenes(updated);
      alert('Scene updated successfully. Downstream assets invalidated if narration changed.');
    } catch (err: any) {
      alert(`Save scene failed: ${err.message || err}`);
    } finally {
      setSavingScene(false);
    }
  };

  const handleMoveScene = async (index: number, direction: 'up' | 'down') => {
    const targetIdx = direction === 'up' ? index - 1 : index + 1;
    if (targetIdx < 0 || targetIdx >= scenes.length) return;

    const newOrder = [...scenes];
    const temp = newOrder[index];
    newOrder[index] = newOrder[targetIdx];
    newOrder[targetIdx] = temp;

    const ids = newOrder.map((s) => s.scene_id);
    setScenes(newOrder);
    setSelectedSceneIndex(targetIdx);

    try {
      await reorderScenes(projectId, ids);
    } catch (err) {
      console.error('Reorder error:', err);
    }
  };

  const handleRunRender = async () => {
    try {
      setRendering(true);
      await runPipeline(projectId, false);
      const updated = await fetchProject(projectId);
      setManifest(updated);
      alert('Rendering complete!');
      setPreviewMode('full');
    } catch (err: any) {
      alert(`Rendering error: ${err.message || err}`);
    } finally {
      setRendering(false);
    }
  };

  const handleReplanStoryboard = async () => {
    if (!confirm('Re-run AI Storyboard Planner? This will refresh scene layouts and visual prompts based on video style.')) return;
    try {
      setLoading(true);
      await planStoryboard(projectId);
      const scList = await fetchScenes(projectId, selectedLocale);
      setScenes(scList);
      if (scList.length > 0) setActiveScene({ ...scList[0] });
    } catch (err: any) {
      alert(`Replan failed: ${err.message || err}`);
    } finally {
      setLoading(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files?.[0] || !activeScene) return;
    try {
      const file = e.target.files[0];
      const item = await uploadMedia(projectId, file);
      setMediaList((prev) => [...prev, item]);
      setActiveScene({ ...activeScene, media_asset_path: item.filename });
    } catch (err: any) {
      alert(`Upload failed: ${err.message || err}`);
    }
  };

  // Video Preview calculation
  const totalDuration = scenes.reduce((sum, s) => sum + (s.estimated_duration_seconds || s.target_duration || 5), 0);
  const currentScene = scenes[selectedSceneIndex];
  const renderedSceneUrl = currentScene
    ? getStorageUrl(`storage/${projectId}/rendered/${selectedLocale}/${currentScene.scene_id}.mp4`)
    : '';
  const finalVideoUrl = manifest?.final_videos?.[selectedLocale]?.video_path
    ? getStorageUrl(manifest.final_videos[selectedLocale].video_path)
    : '';

  const activeVideoUrl = previewMode === 'full' && finalVideoUrl ? finalVideoUrl : renderedSceneUrl;

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play();
    }
    setIsPlaying(!isPlaying);
  };

  if (loading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center space-y-3">
        <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
        <p className="text-sm text-slate-400">Loading Video Studio...</p>
      </div>
    );
  }

  return (
    <div className="max-w-[1600px] mx-auto px-4 sm:px-6 py-6 space-y-6">
      {/* Studio Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 p-4 rounded-xl bg-slate-900 border border-slate-800">
        <div className="flex items-center gap-4">
          <Link
            href="/"
            className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
          >
            <RotateCcw className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-lg font-extrabold text-white">
                {manifest?.source_request.topic || 'Training Project'}
              </h1>
              <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-slate-800 text-cyan-400 border border-slate-700">
                {manifest?.status || 'Draft'}
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Style: <span className="text-slate-200 capitalize">{manifest?.source_request.video_style?.replace(/_/g, ' ')}</span> • Presenter: <span className="text-slate-200 capitalize">{manifest?.avatar_provider}</span>
            </p>
          </div>
        </div>

        {/* Locale Matrix & Actions */}
        <div className="flex items-center gap-3">
          {/* Target Language Switcher */}
          <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800">
            <Globe2 className="w-3.5 h-3.5 text-cyan-400" />
            <select
              value={selectedLocale}
              onChange={(e) => handleLocaleChange(e.target.value)}
              className="bg-transparent text-xs text-white font-medium focus:outline-none cursor-pointer"
            >
              {(manifest?.source_request.target_languages || ['ar-SA', 'en-US']).map((loc) => (
                <option key={loc} value={loc} className="bg-slate-900">
                  {loc === 'ar-SA' ? '🇸🇦 Arabic (Saudi)' : loc === 'en-US' ? '🇺🇸 English (US)' : loc}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={handleReplanStoryboard}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition-colors"
          >
            <Wand2 className="w-3.5 h-3.5 text-cyan-400" />
            <span>AI Storyboard</span>
          </button>

          <button
            onClick={handleRunRender}
            disabled={rendering}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-sky-500 hover:from-cyan-400 hover:to-sky-400 text-slate-950 text-xs font-bold shadow-md shadow-cyan-500/20 transition-all disabled:opacity-50"
          >
            <Sparkles className="w-3.5 h-3.5" />
            <span>{rendering ? 'Rendering...' : 'Render Video'}</span>
          </button>

          <Link
            href={`/studio/${projectId}/export`}
            className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-emerald-500 hover:bg-emerald-400 text-slate-950 text-xs font-bold shadow-md shadow-emerald-500/20 transition-all"
          >
            <Download className="w-3.5 h-3.5" />
            <span>Export</span>
          </Link>
        </div>
      </div>

      {/* 3-Column Studio Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* LEFT: Scene List (3 cols) */}
        <div className="lg:col-span-3 rounded-xl bg-slate-900/90 border border-slate-800 p-4 space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-slate-800">
            <span className="text-xs font-bold text-white uppercase tracking-wider flex items-center gap-1.5">
              <Film className="w-3.5 h-3.5 text-cyan-400" />
              Scenes ({scenes.length})
            </span>
            <span className="text-[11px] font-mono text-slate-400">{totalDuration.toFixed(0)}s total</span>
          </div>

          <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
            {scenes.map((sc, idx) => {
              const isSelected = idx === selectedSceneIndex;
              const isPresenter = sc.media_type === 'presenter' || sc.avatar_enabled;
              const isQuiz = sc.media_type === 'quiz';

              return (
                <div
                  key={sc.scene_id}
                  onClick={() => setSelectedSceneIndex(idx)}
                  className={`p-3 rounded-xl border cursor-pointer transition-all flex items-start justify-between gap-2 ${
                    isSelected
                      ? 'bg-cyan-950/40 border-cyan-500/90 shadow-md shadow-cyan-500/10'
                      : 'bg-slate-950/60 border-slate-800/80 hover:border-slate-700'
                  }`}
                >
                  <div className="space-y-1 overflow-hidden">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-300">
                        #{idx + 1}
                      </span>
                      <span className="text-xs font-bold text-white truncate max-w-[140px]">
                        {sc.title}
                      </span>
                    </div>

                    <div className="flex items-center gap-1.5 text-[10px]">
                      <span
                        className={`px-1.5 py-0.5 rounded font-medium capitalize ${
                          isPresenter
                            ? 'bg-purple-950/80 text-purple-300 border border-purple-800/60'
                            : isQuiz
                            ? 'bg-amber-950/80 text-amber-300 border border-amber-800/60'
                            : 'bg-slate-800 text-slate-300'
                        }`}
                      >
                        {sc.media_type || 'presenter'}
                      </span>
                      <span className="text-slate-400 font-mono">
                        {(sc.estimated_duration_seconds || sc.target_duration || 5)}s
                      </span>
                    </div>
                  </div>

                  {/* Reorder Buttons */}
                  <div className="flex flex-col gap-1" onClick={(e) => e.stopPropagation()}>
                    <button
                      onClick={() => handleMoveScene(idx, 'up')}
                      disabled={idx === 0}
                      className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 disabled:opacity-20"
                    >
                      <ChevronUp className="w-3 h-3" />
                    </button>
                    <button
                      onClick={() => handleMoveScene(idx, 'down')}
                      disabled={idx === scenes.length - 1}
                      className="p-1 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 disabled:opacity-20"
                    >
                      <ChevronDown className="w-3 h-3" />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* CENTER: 16:9 Video Preview (6 cols) */}
        <div className="lg:col-span-6 space-y-4">
          <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden shadow-xl">
            {/* 16:9 Video Container */}
            <div className="relative aspect-video w-full bg-black flex items-center justify-center overflow-hidden">
              {activeVideoUrl ? (
                <video
                  ref={videoRef}
                  src={activeVideoUrl}
                  className="w-full h-full object-contain"
                  onTimeUpdate={() => {
                    if (videoRef.current) {
                      setCurrentTime(videoRef.current.currentTime);
                      setDuration(videoRef.current.duration || 0);
                    }
                  }}
                  onEnded={() => setIsPlaying(false)}
                />
              ) : (
                /* Composition Canvas Placeholder */
                <div className="w-full h-full bg-[#090D1A] flex flex-col items-center justify-center p-6 text-center space-y-3 relative">
                  <div className="w-16 h-16 rounded-2xl bg-cyan-950/40 border border-cyan-800/60 flex items-center justify-center text-cyan-400">
                    <User className="w-8 h-8" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">
                      {currentScene?.title || 'Scene Ready for Composition'}
                    </h3>
                    <p className="text-xs text-slate-400 mt-1 max-w-sm">
                      Layout: <span className="text-cyan-400 font-mono">{currentScene?.layout_type || 'presenter_split'}</span> ({currentScene?.media_type || 'presenter'})
                    </p>
                  </div>

                  {/* Subtitle Safe Zone Mock */}
                  <div className="absolute bottom-6 left-8 right-8 py-2 px-4 rounded bg-black/75 border border-slate-800 text-xs text-cyan-300 font-medium text-center">
                    {currentScene?.narration || 'Subtitle preview safe zone (Arabic RTL / ASS enabled)'}
                  </div>
                </div>
              )}

              {/* Mode Pill overlay */}
              <div className="absolute top-3 right-3 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/70 backdrop-blur-md text-[11px] font-mono text-slate-300 border border-slate-800">
                <span className="w-2 h-2 rounded-full bg-cyan-400 inline-block"></span>
                <span>{previewMode === 'full' ? 'Full Video' : `Scene #${selectedSceneIndex + 1}`}</span>
              </div>
            </div>

            {/* Playback Controls Bar */}
            <div className="p-3 bg-slate-950 border-t border-slate-800 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <button
                  onClick={togglePlay}
                  className="p-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 transition-colors"
                >
                  {isPlaying ? <Pause className="w-4 h-4 fill-current" /> : <Play className="w-4 h-4 fill-current ml-0.5" />}
                </button>
                <div className="text-xs font-mono text-slate-400">
                  {currentTime.toFixed(1)}s / {duration > 0 ? duration.toFixed(1) : (currentScene?.estimated_duration_seconds || 5)}s
                </div>
              </div>

              <div className="flex items-center gap-2 text-xs">
                <button
                  onClick={() => setPreviewMode('scene')}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                    previewMode === 'scene' ? 'bg-slate-800 text-cyan-400' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Scene
                </button>
                <button
                  onClick={() => setPreviewMode('full')}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                    previewMode === 'full' ? 'bg-slate-800 text-cyan-400' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  Full Multilingual
                </button>
              </div>
            </div>
          </div>

          {/* Interactive Timeline Strip */}
          <div className="rounded-xl bg-slate-900 border border-slate-800 p-4 space-y-2">
            <div className="flex justify-between text-xs text-slate-400">
              <span className="font-semibold text-white">Timeline Sequence</span>
              <span className="font-mono text-cyan-400">{totalDuration.toFixed(1)}s Total Duration</span>
            </div>

            {/* Visual Timeline Blocks */}
            <div className="flex items-center gap-1.5 h-12 w-full bg-slate-950 p-1 rounded-lg border border-slate-800/80 overflow-x-auto">
              {scenes.map((sc, idx) => {
                const isSelected = idx === selectedSceneIndex;
                const dur = sc.estimated_duration_seconds || sc.target_duration || 5;
                const widthPercent = Math.max((dur / totalDuration) * 100, 10);

                return (
                  <div
                    key={sc.scene_id}
                    onClick={() => setSelectedSceneIndex(idx)}
                    style={{ width: `${widthPercent}%` }}
                    className={`h-full rounded cursor-pointer transition-all flex flex-col items-center justify-center text-[10px] font-mono px-1 truncate ${
                      isSelected
                        ? 'bg-gradient-to-r from-cyan-600 to-sky-600 text-white font-bold border border-cyan-400'
                        : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                    }`}
                  >
                    <span className="truncate w-full text-center">#{idx + 1} {sc.media_type}</span>
                    <span className="text-[9px] opacity-80">{dur}s</span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* RIGHT: Scene Inspector (3 cols) */}
        {activeScene && (
          <div className="lg:col-span-3 rounded-xl bg-slate-900 border border-slate-800 p-4 space-y-4">
            <div className="flex items-center justify-between pb-2 border-b border-slate-800">
              <span className="text-xs font-bold text-white uppercase tracking-wider">
                Scene Inspector (#{selectedSceneIndex + 1})
              </span>
              <button
                onClick={handleSaveScene}
                disabled={savingScene}
                className="flex items-center gap-1 px-3 py-1 rounded bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-bold text-xs shadow-sm transition-all"
              >
                <Save className="w-3 h-3" />
                <span>{savingScene ? 'Saving...' : 'Apply'}</span>
              </button>
            </div>

            <div className="space-y-3.5 text-xs">
              {/* Scene Title */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Scene Title</label>
                <input
                  type="text"
                  value={activeScene.title || ''}
                  onChange={(e) => setActiveScene({ ...activeScene, title: e.target.value })}
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-white focus:outline-none focus:border-cyan-500"
                />
              </div>

              {/* Media Type */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Media Source Type</label>
                <select
                  value={activeScene.media_type || 'presenter'}
                  onChange={(e) =>
                    setActiveScene({
                      ...activeScene,
                      media_type: e.target.value as SceneMediaType,
                      avatar_enabled: e.target.value === 'presenter' || e.target.value === 'outro',
                    })
                  }
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-white focus:outline-none"
                >
                  <option value="presenter">Presenter (Talking Avatar)</option>
                  <option value="broll">B-Roll Footage</option>
                  <option value="motion_visual">Cinematic Motion Visual</option>
                  <option value="uploaded_video">Uploaded Video Clip</option>
                  <option value="uploaded_image">Uploaded Still Image</option>
                  <option value="quiz">Interactive Video Quiz</option>
                  <option value="outro">Outro / Call to Action</option>
                </select>
              </div>

              {/* Layout Type */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Layout Composition</label>
                <select
                  value={activeScene.layout_type || 'presenter_split'}
                  onChange={(e) =>
                    setActiveScene({ ...activeScene, layout_type: e.target.value as SceneLayoutType })
                  }
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-white focus:outline-none"
                >
                  <option value="presenter_split">Presenter Split (42% Avatar / 58% Media)</option>
                  <option value="presenter_full">Presenter Full (Centered Studio)</option>
                  <option value="media_full">Media Full Screen</option>
                  <option value="media_with_overlay">Media + Keyphrase Overlay</option>
                  <option value="quiz_card">Quiz Assessment Card</option>
                </select>
              </div>

              {/* Avatar Toggle & Placement */}
              <div className="flex items-center justify-between p-2 rounded-lg bg-slate-950 border border-slate-800">
                <div>
                  <div className="font-semibold text-white">Presenter Active</div>
                  <div className="text-[10px] text-slate-400">Generate Lipsynced Avatar</div>
                </div>
                <input
                  type="checkbox"
                  checked={Boolean(activeScene.avatar_enabled)}
                  onChange={(e) => setActiveScene({ ...activeScene, avatar_enabled: e.target.checked })}
                  className="w-4 h-4 accent-cyan-400 rounded cursor-pointer"
                />
              </div>

              {/* Narration */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium flex justify-between">
                  <span>Narration ({selectedLocale})</span>
                  <span className="text-[10px] text-amber-400">Edits invalidate audio</span>
                </label>
                <textarea
                  rows={3}
                  value={activeScene.narration || ''}
                  onChange={(e) => setActiveScene({ ...activeScene, narration: e.target.value })}
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-white focus:outline-none focus:border-cyan-500 text-xs"
                />
              </div>

              {/* On-screen text */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">On-Screen Text Headline</label>
                <input
                  type="text"
                  value={activeScene.on_screen_text || ''}
                  onChange={(e) => setActiveScene({ ...activeScene, on_screen_text: e.target.value })}
                  placeholder="e.g. تحمير الدجاج أو التحقق من الرابط"
                  className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-white focus:outline-none"
                />
              </div>

              {/* Media Library Asset Selection */}
              <div>
                <label className="block text-slate-400 mb-1 font-medium">Assigned Media Asset</label>
                <div className="flex gap-2">
                  <select
                    value={activeScene.media_asset_path || ''}
                    onChange={(e) => setActiveScene({ ...activeScene, media_asset_path: e.target.value })}
                    className="w-full px-3 py-1.5 rounded-lg bg-slate-950 border border-slate-800 text-white focus:outline-none text-xs"
                  >
                    <option value="">None (Auto Motion Visual)</option>
                    {mediaList.map((m) => (
                      <option key={m.filename} value={m.filename}>
                        {m.filename} ({m.media_type})
                      </option>
                    ))}
                  </select>
                  <label className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 cursor-pointer flex items-center justify-center border border-slate-700">
                    <Upload className="w-3.5 h-3.5 text-cyan-400" />
                    <input type="file" className="hidden" onChange={handleFileUpload} />
                  </label>
                </div>
              </div>

              {/* Quiz Data Fields (if quiz scene) */}
              {activeScene.media_type === 'quiz' && (
                <div className="p-3 rounded-lg bg-slate-950 border border-amber-900/40 space-y-2">
                  <div className="font-bold text-amber-300 text-[11px]">Quiz Assessment Settings</div>
                  <div>
                    <label className="block text-slate-400 text-[10px] mb-0.5">Question Prompt</label>
                    <input
                      type="text"
                      value={activeScene.quiz_data?.question || activeScene.title || ''}
                      onChange={(e) =>
                        setActiveScene({
                          ...activeScene,
                          quiz_data: {
                            question: e.target.value,
                            options: activeScene.quiz_data?.options || ['Option A', 'Option B', 'Option C'],
                            correct_index: activeScene.quiz_data?.correct_index || 0,
                          },
                        })
                      }
                      className="w-full px-2 py-1 rounded bg-slate-900 border border-slate-800 text-white text-xs"
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
