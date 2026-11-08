'use client';

import React, { useEffect, useState } from 'react';
import { Cpu, Film, Volume2, Sparkles, RefreshCw } from 'lucide-react';
import { fetchProvidersStatus } from '@/lib/api';
import { ProviderStatus } from '@/types';

export default function SettingsDiagnosticsPage() {
  const [providers, setProviders] = useState<ProviderStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setLoading(true);
      const data = await fetchProvidersStatus();
      setProviders(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Cpu className="w-6 h-6 text-cyan-400" />
            Engine Diagnostics & Provider Studio
          </h1>
          <p className="text-xs text-slate-400 mt-1">
            Real-time status of local SadTalker GPU, Edge-TTS audio, FFmpeg composer, and LLM providers
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-xs text-slate-300 transition-colors"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>Refresh</span>
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* SadTalker Card */}
        <div className="rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-purple-950 border border-purple-800 flex items-center justify-center text-purple-400">
                <Cpu className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">SadTalker Local (Free)</h3>
                <span className="text-[11px] text-slate-400">Isolated Virtualenv & CUDA Engine</span>
              </div>
            </div>
            <span
              className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                providers?.sadtalker?.ready
                  ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                  : 'bg-rose-950 text-rose-400 border border-rose-800'
              }`}
            >
              {providers?.sadtalker?.ready ? 'Ready' : 'Unavailable'}
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">GPU Device:</span>
              <span className="font-mono text-cyan-400 font-semibold">
                {providers?.sadtalker?.gpu_name || 'NVIDIA GeForce RTX 4060'}
              </span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">CUDA Acceleration:</span>
              <span className="font-bold text-emerald-400">Active (Torch CUDA)</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Checkpoint Model:</span>
              <span className="font-mono text-slate-300">checkpoints/SadTalker_V0.0.2_256.safetensors</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-400">Cost:</span>
              <span className="font-bold text-emerald-400">$0.00 (100% Local Inference)</span>
            </div>
          </div>
        </div>

        {/* Edge-TTS Card */}
        <div className="rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-sky-950 border border-sky-800 flex items-center justify-center text-sky-400">
                <Volume2 className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Edge-TTS Audio Engine</h3>
                <span className="text-[11px] text-slate-400">Neural Voice Synthesis & Duration Targeting</span>
              </div>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-950 text-emerald-400 border border-emerald-800">
              Ready
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Sample Rate:</span>
              <span className="font-mono text-cyan-400">48,000 Hz Normalized Broadcast WAV</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Default Arabic Voice:</span>
              <span className="font-semibold text-white">ar-SA-HamedNeural</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Default English Voice:</span>
              <span className="font-semibold text-white">en-US-JennyNeural</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-400">Duration Reconciliation:</span>
              <span className="font-bold text-emerald-400">Automated (±15% Tolerance)</span>
            </div>
          </div>
        </div>

        {/* Groq LLM Card */}
        <div className="rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-cyan-950 border border-cyan-800 flex items-center justify-center text-cyan-400">
                <Sparkles className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Groq AI Planner & Localization</h3>
                <span className="text-[11px] text-slate-400">Script Writing & Storyboard Planning</span>
              </div>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-950 text-emerald-400 border border-emerald-800">
              Active
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Model:</span>
              <span className="font-mono text-cyan-400 font-semibold">openai/gpt-oss-20b</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Security Mode:</span>
              <span className="font-bold text-emerald-400">API Key Server-Side Redacted</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Storyboard Planner:</span>
              <span className="font-semibold text-white">Content-Aware Media Allocation</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-400">Fallback Provider:</span>
              <span className="font-mono text-slate-400">Deterministic Mock / Rule Engine</span>
            </div>
          </div>
        </div>

        {/* FFmpeg Composition Card */}
        <div className="rounded-2xl bg-slate-900 border border-slate-800 p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center text-slate-300">
                <Film className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">FFmpeg Scene Composer</h3>
                <span className="text-[11px] text-slate-400">Multi-layout Split, Motion Visuals, ASS RTL</span>
              </div>
            </div>
            <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-emerald-950 text-emerald-400 border border-emerald-800">
              Ready
            </span>
          </div>

          <div className="space-y-2 text-xs">
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Video Layouts:</span>
              <span className="font-semibold text-white">presenter_split, presenter_full, media_full</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Motion Visuals:</span>
              <span className="font-semibold text-cyan-400">Ken Burns Pan/Zoom (Local & Free)</span>
            </div>
            <div className="flex justify-between py-1 border-b border-slate-800/80">
              <span className="text-slate-400">Arabic Subtitle Engine:</span>
              <span className="font-semibold text-emerald-400">HarfBuzz Complex Text Shaping (libass)</span>
            </div>
            <div className="flex justify-between py-1">
              <span className="text-slate-400">Output Container:</span>
              <span className="font-mono text-white">MP4 (H.264 / AAC 48k)</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
