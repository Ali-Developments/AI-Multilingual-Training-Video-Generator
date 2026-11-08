'use client';

import React, { useEffect, useState, useRef, useCallback } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  Download,
  Film,
  CheckCircle2,
  Globe2,
  Sparkles,
  ArrowLeft,
  FileAudio,
  FileText,
  RefreshCw,
} from 'lucide-react';
import { fetchProject, getStorageUrl, runPipeline } from '@/lib/api';
import { ProjectManifest, FinalVideoAsset } from '@/types';

export default function ExportDashboardPage() {
  const params = useParams();
  const projectId = params?.id as string;

  const [manifest, setManifest] = useState<ProjectManifest | null>(null);
  const [selectedLocale, setSelectedLocale] = useState('ar-SA');
  const [loading, setLoading] = useState(true);
  const [rendering, setRendering] = useState(false);

  const videoRef = useRef<HTMLVideoElement | null>(null);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const proj = await fetchProject(projectId);
      setManifest(proj);

      const locales = proj.source_request.target_languages || [proj.source_request.base_language || 'en-US'];
      const defaultLoc = locales.includes('ar-SA') ? 'ar-SA' : locales[0];
      setSelectedLocale(defaultLoc);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (projectId) {
      loadData();
    }
  }, [projectId, loadData]);

  const activeVideo: FinalVideoAsset | undefined = manifest?.final_videos?.[selectedLocale];
  const videoUrl = activeVideo?.video_path ? getStorageUrl(activeVideo.video_path) : '';

  const scenes = manifest?.final_script?.scenes || [];
  const presenterScenesCount = scenes.filter((s) => s.media_type === 'presenter' || s.avatar_enabled).length;
  const mediaScenesCount = scenes.length - presenterScenesCount;

  const handleRender = async () => {
    try {
      setRendering(true);
      await runPipeline(projectId, false);
      await loadData();
      alert('Video rendering complete!');
    } catch (err: any) {
      alert(`Render failed: ${err.message || err}`);
    } finally {
      setRendering(false);
    }
  };

  if (loading) {
    return (
      <div className="py-24 flex flex-col items-center justify-center space-y-3">
        <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
        <p className="text-sm text-slate-400">Loading export dashboard...</p>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div>
        <Link
          href={`/studio/${projectId}`}
          className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-cyan-400 mb-3 transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Scene Studio</span>
        </Link>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white">Video Export & Delivery</h1>
            <p className="text-xs sm:text-sm text-slate-400 mt-1">
              {manifest?.source_request.topic} • 1920×1080 H.264 / 48kHz AAC Normalized Audio
            </p>
          </div>

          {/* Locale Picker */}
          <div className="flex items-center gap-2 p-1.5 rounded-xl bg-slate-900 border border-slate-800">
            <Globe2 className="w-4 h-4 text-cyan-400 ml-1.5" />
            <select
              value={selectedLocale}
              onChange={(e) => setSelectedLocale(e.target.value)}
              className="bg-transparent text-xs text-white font-semibold focus:outline-none pr-2 cursor-pointer"
            >
              {(manifest?.source_request.target_languages || ['ar-SA', 'en-US']).map((loc) => (
                <option key={loc} value={loc} className="bg-slate-900">
                  {loc === 'ar-SA' ? '🇸🇦 Arabic (Saudi Arabia)' : loc === 'en-US' ? '🇺🇸 English (US)' : loc}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Main Preview & Details Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left: 16:9 Video Player (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          <div className="rounded-2xl bg-slate-900 border border-slate-800 overflow-hidden shadow-2xl">
            <div className="relative aspect-video w-full bg-black flex items-center justify-center">
              {videoUrl ? (
                <video
                  ref={videoRef}
                  src={videoUrl}
                  controls
                  className="w-full h-full object-contain"
                />
              ) : (
                <div className="w-full h-full bg-[#090D1A] flex flex-col items-center justify-center p-8 text-center space-y-3">
                  <Film className="w-12 h-12 text-slate-700" />
                  <h3 className="text-base font-bold text-white">Final video not yet composed</h3>
                  <p className="text-xs text-slate-400 max-w-sm">
                    All scenes are planned and ready for final rendering with SadTalker avatar lipsync, ASS subtitles, and 48kHz normalized audio.
                  </p>
                  <button
                    onClick={handleRender}
                    disabled={rendering}
                    className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-bold text-xs shadow-lg shadow-cyan-500/20 transition-all disabled:opacity-50"
                  >
                    <Sparkles className="w-4 h-4" />
                    <span>{rendering ? 'Rendering in Progress...' : 'Render Final Video Now'}</span>
                  </button>
                </div>
              )}
            </div>

            {/* Video Meta bar */}
            <div className="p-3 bg-slate-950 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
              <span className="font-mono">1920×1080 @ 30 FPS</span>
              <span className="font-mono text-cyan-400 font-semibold">
                Duration: {activeVideo?.duration_seconds ? `${activeVideo.duration_seconds.toFixed(1)}s` : `${manifest?.source_request.target_duration_seconds || 30}s (Target)`}
              </span>
            </div>
          </div>
        </div>

        {/* Right: Technical Specs & Download Panel (5 cols) */}
        <div className="lg:col-span-5 space-y-6">
          {/* Production Card */}
          <div className="rounded-2xl bg-slate-900/90 border border-slate-800 p-6 space-y-4">
            <h2 className="text-sm font-bold text-white uppercase tracking-wider flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-400" />
              Delivery Manifest ({selectedLocale})
            </h2>

            <div className="space-y-3 text-xs">
              <div className="flex justify-between py-1.5 border-b border-slate-800/80">
                <span className="text-slate-400">Target Locale:</span>
                <span className="font-bold text-white">{selectedLocale}</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-800/80">
                <span className="text-slate-400">Total Duration:</span>
                <span className="font-mono text-cyan-400 font-bold">
                  {activeVideo?.duration_seconds ? `${activeVideo.duration_seconds.toFixed(1)} seconds` : 'Pending render'}
                </span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-800/80">
                <span className="text-slate-400">Resolution:</span>
                <span className="font-mono text-white">1920 × 1080 (16:9 Full HD)</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-800/80">
                <span className="text-slate-400">Presenter Avatar Scenes:</span>
                <span className="font-bold text-purple-300">{presenterScenesCount} scenes</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-800/80">
                <span className="text-slate-400">Motion Visual & B-Roll Scenes:</span>
                <span className="font-bold text-sky-300">{mediaScenesCount} scenes</span>
              </div>
              <div className="flex justify-between py-1.5 border-b border-slate-800/80">
                <span className="text-slate-400">Subtitles:</span>
                <span className="font-bold text-emerald-400">libass HarfBuzz RTL Burned</span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-slate-400">Status:</span>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-950 text-emerald-400 border border-emerald-800">
                  {activeVideo?.status || manifest?.status || 'Pending'}
                </span>
              </div>
            </div>

            {/* Download Buttons */}
            <div className="space-y-2.5 pt-4">
              {videoUrl ? (
                <a
                  href={videoUrl}
                  download={`training_${selectedLocale}.mp4`}
                  className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-gradient-to-r from-cyan-500 to-sky-500 hover:from-cyan-400 hover:to-sky-400 text-slate-950 font-bold text-sm shadow-lg shadow-cyan-500/25 transition-all text-center"
                >
                  <Download className="w-4 h-4" />
                  <span>Download Final MP4</span>
                </a>
              ) : (
                <button
                  onClick={handleRender}
                  disabled={rendering}
                  className="w-full flex items-center justify-center gap-2 px-5 py-3 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-bold text-sm shadow-md transition-all disabled:opacity-50"
                >
                  <Sparkles className="w-4 h-4" />
                  <span>{rendering ? 'Rendering...' : 'Render to Enable Download'}</span>
                </button>
              )}

              <div className="grid grid-cols-2 gap-2 text-xs">
                <a
                  href={getStorageUrl(`storage/${projectId}/audio/${selectedLocale}/full_track.wav`)}
                  download={`audio_${selectedLocale}.wav`}
                  className="p-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center justify-center gap-1.5 transition-colors"
                >
                  <FileAudio className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Audio (48k)</span>
                </a>
                <a
                  href={getStorageUrl(`storage/${projectId}/subtitles/${selectedLocale}/full.srt`)}
                  download={`subtitles_${selectedLocale}.srt`}
                  className="p-2.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 flex items-center justify-center gap-1.5 transition-colors"
                >
                  <FileText className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Subtitles (SRT)</span>
                </a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
