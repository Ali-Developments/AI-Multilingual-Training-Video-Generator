'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  PlusCircle,
  Play,
  Clock,
  Globe2,
  Sparkles,
  Copy,
  Trash2,
  ArrowRight,
  RefreshCw,
  Video,
  CheckCircle2,
  Film,
  User,
} from 'lucide-react';
import {
  fetchProjectSummaries,
  duplicateProject,
  deleteProject,
  fetchProvidersStatus,
  getStorageUrl,
} from '@/lib/api';
import { ProjectSummary, ProviderStatus } from '@/types';

export default function DashboardPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [providers, setProviders] = useState<ProviderStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoadingId, setActionLoadingId] = useState<string | null>(null);

  const loadData = async () => {
    try {
      setLoading(true);
      const [sums, provs] = await Promise.all([
        fetchProjectSummaries().catch(() => []),
        fetchProvidersStatus().catch(() => null),
      ]);
      setProjects(sums);
      setProviders(provs);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleDuplicate = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      setActionLoadingId(id);
      await duplicateProject(id);
      await loadData();
    } catch (err) {
      alert(`Duplicate failed: ${err}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm('Are you sure you want to delete this project?')) return;
    try {
      setActionLoadingId(id);
      await deleteProject(id);
      await loadData();
    } catch (err) {
      alert(`Delete failed: ${err}`);
    } finally {
      setActionLoadingId(null);
    }
  };

  const completedCount = projects.filter((p) => p.status === 'completed').length;

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      {/* Studio Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-slate-900 via-slate-800 to-cyan-950/40 border border-slate-800 p-8 shadow-xl">
        <div className="relative z-10 max-w-3xl space-y-4">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/80 border border-cyan-800 text-cyan-300 text-xs font-semibold">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Next-Generation Presenter-Led AI Video Engine</span>
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white">
            AI Training Video Studio
          </h1>
          <p className="text-slate-300 text-base sm:text-lg leading-relaxed">
            Create professional presenter-led training videos. Moving local avatars, cinematic
            motion visuals, intelligent storyboard planning, and cultural multilingual dubbing —
            free from slide templates and PowerPoint layouts.
          </p>

          <div className="pt-2 flex flex-wrap items-center gap-4">
            <Link
              href="/create"
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-bold text-sm shadow-lg shadow-cyan-500/25 transition-all"
            >
              <PlusCircle className="w-4 h-4" />
              <span>Create New Video</span>
            </Link>
            <Link
              href="/media"
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 font-medium text-sm transition-all"
            >
              <Video className="w-4 h-4 text-cyan-400" />
              <span>Media Library</span>
            </Link>
          </div>
        </div>

        {/* Decorative background glow */}
        <div className="absolute right-0 top-0 -mt-12 -mr-12 w-96 h-96 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
          <div className="text-xs text-slate-400 font-medium flex items-center gap-1.5 mb-1">
            <Film className="w-3.5 h-3.5 text-cyan-400" />
            Total Projects
          </div>
          <div className="text-2xl font-bold text-white">{projects.length}</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
          <div className="text-xs text-slate-400 font-medium flex items-center gap-1.5 mb-1">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
            Completed Videos
          </div>
          <div className="text-2xl font-bold text-white">{completedCount}</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
          <div className="text-xs text-slate-400 font-medium flex items-center gap-1.5 mb-1">
            <Globe2 className="w-3.5 h-3.5 text-sky-400" />
            Multilingual Support
          </div>
          <div className="text-2xl font-bold text-white">ar-SA + 5 More</div>
        </div>

        <div className="p-4 rounded-xl bg-slate-900/60 border border-slate-800/80">
          <div className="text-xs text-slate-400 font-medium flex items-center gap-1.5 mb-1">
            <User className="w-3.5 h-3.5 text-purple-400" />
            Local Presenter Engine
          </div>
          <div className="text-sm font-semibold text-emerald-400 flex items-center gap-1 mt-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400 inline-block animate-pulse"></span>
            {providers?.sadtalker?.gpu_available ? 'SadTalker (CUDA RTX)' : 'SadTalker Ready'}
          </div>
        </div>
      </div>

      {/* Recent Projects Header */}
      <div className="flex items-center justify-between pt-2">
        <div>
          <h2 className="text-xl font-bold text-white">Recent Projects</h2>
          <p className="text-xs text-slate-400">Manage, edit scenes, or render final training videos</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 font-medium transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      {/* Projects Grid */}
      {loading ? (
        <div className="py-20 flex flex-col items-center justify-center space-y-3">
          <RefreshCw className="w-8 h-8 text-cyan-400 animate-spin" />
          <p className="text-sm text-slate-400">Loading training projects...</p>
        </div>
      ) : projects.length === 0 ? (
        <div className="py-16 text-center rounded-2xl border border-dashed border-slate-800 bg-slate-900/20 p-8 space-y-4">
          <div className="w-12 h-12 rounded-xl bg-slate-800 flex items-center justify-center mx-auto text-slate-400">
            <Film className="w-6 h-6" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">No projects created yet</h3>
            <p className="text-sm text-slate-400 max-w-sm mx-auto mt-1">
              Start by launching the project creation wizard with your training topic and target languages.
            </p>
          </div>
          <Link
            href="/create"
            className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 font-bold text-sm shadow-md transition-all"
          >
            <PlusCircle className="w-4 h-4" />
            <span>Create First Video</span>
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {projects.map((proj) => {
            const isCompleted = proj.status === 'completed';
            const isRendering = proj.status === 'running';
            const thumbUrl = getStorageUrl(proj.thumbnail_path);

            return (
              <div
                key={proj.project_id}
                onClick={() => router.push(`/studio/${proj.project_id}`)}
                className="group relative cursor-pointer rounded-xl bg-slate-900/80 border border-slate-800 hover:border-cyan-500/50 shadow-md hover:shadow-cyan-500/10 transition-all flex flex-col overflow-hidden"
              >
                {/* 16:9 Thumbnail Area */}
                <div className="relative aspect-video w-full bg-slate-950 overflow-hidden flex items-center justify-center border-b border-slate-800">
                  {thumbUrl ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={thumbUrl}
                      alt={proj.title}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    />
                  ) : (
                    <div className="w-full h-full bg-gradient-to-br from-slate-900 via-slate-950 to-cyan-950/20 flex flex-col items-center justify-center text-slate-600 gap-2">
                      <Film className="w-8 h-8 text-slate-700" />
                      <span className="text-[11px] font-mono uppercase tracking-wider text-slate-500">
                        {proj.project_id}
                      </span>
                    </div>
                  )}

                  {/* Play Overlay */}
                  <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                    <div className="w-12 h-12 rounded-full bg-cyan-400 text-slate-950 flex items-center justify-center shadow-lg shadow-cyan-500/50 transform scale-90 group-hover:scale-100 transition-transform">
                      <Play className="w-5 h-5 fill-current ml-0.5" />
                    </div>
                  </div>

                  {/* Duration Pill */}
                  <div className="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-black/80 backdrop-blur-sm text-[11px] font-mono text-slate-200 flex items-center gap-1">
                    <Clock className="w-3 h-3 text-cyan-400" />
                    <span>{proj.duration_seconds.toFixed(1)}s</span>
                  </div>

                  {/* Status Badge */}
                  <div className="absolute top-2 left-2">
                    <span
                      className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider ${
                        isCompleted
                          ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                          : isRendering
                          ? 'bg-cyan-950 text-cyan-400 border border-cyan-800 animate-pulse'
                          : 'bg-slate-800 text-slate-300 border border-slate-700'
                      }`}
                    >
                      {proj.status}
                    </span>
                  </div>
                </div>

                {/* Card Content */}
                <div className="p-4 flex-1 flex flex-col justify-between space-y-3">
                  <div>
                    <h3 className="text-base font-bold text-white group-hover:text-cyan-400 transition-colors line-clamp-1">
                      {proj.title}
                    </h3>

                    {/* Language & Provider Metadata */}
                    <div className="flex flex-wrap items-center gap-1.5 mt-2">
                      <span className="px-2 py-0.5 rounded bg-slate-800 text-[11px] font-medium text-slate-300">
                        {proj.source_language}
                      </span>
                      {proj.target_languages.map((t) => (
                        <span
                          key={t}
                          className="px-2 py-0.5 rounded bg-cyan-950/60 border border-cyan-900/60 text-[11px] font-medium text-cyan-300"
                        >
                          {t}
                        </span>
                      ))}
                      <span className="px-2 py-0.5 rounded bg-slate-800/80 text-[11px] text-slate-400 ml-auto capitalize">
                        {proj.avatar_provider}
                      </span>
                    </div>
                  </div>

                  {/* Card Actions Footer */}
                  <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-xs">
                    <span className="text-[11px] text-slate-500 font-mono">
                      {new Date(proj.updated_at).toLocaleDateString()}
                    </span>

                    <div className="flex items-center gap-1.5">
                      <button
                        title="Duplicate Project"
                        onClick={(e) => handleDuplicate(e, proj.project_id)}
                        disabled={actionLoadingId === proj.project_id}
                        className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-slate-200 transition-colors"
                      >
                        <Copy className="w-3.5 h-3.5" />
                      </button>
                      <button
                        title="Delete Project"
                        onClick={(e) => handleDelete(e, proj.project_id)}
                        disabled={actionLoadingId === proj.project_id}
                        className="p-1.5 rounded hover:bg-rose-950 text-slate-400 hover:text-rose-400 transition-colors"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                      <div className="inline-flex items-center gap-1 font-semibold text-cyan-400 hover:text-cyan-300 pl-1">
                        <span>Studio</span>
                        <ArrowRight className="w-3.5 h-3.5 group-hover:translate-x-0.5 transition-transform" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
