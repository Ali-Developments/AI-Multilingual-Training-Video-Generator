'use client';

import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import {
  Sparkles,
  ArrowRight,
  ArrowLeft,
  Globe2,
  Palette,
  User,
  CheckCircle2,
  Layers,
  Wand2,
  Cpu,
  BookOpen,
  AlertCircle,
} from 'lucide-react';
import { createProject, runPipeline, generateScript, planStoryboard } from '@/lib/api';
import { VideoStyle, serializeCreateProjectRequest } from '@/types';

export default function CreateVideoWizard() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const isSubmittingRef = React.useRef(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Form State
  const [topic, setTopic] = useState('Workplace Phishing Defense Essentials');
  const [sourceContent, setSourceContent] = useState(
    'Identify suspicious emails, check sender domain names, never click unexpected attachments or links, and report threats immediately to cybersecurity operations.'
  );
  const [audience, setAudience] = useState('Corporate Employees & Staff');
  const [duration, setDuration] = useState(30);
  const [baseLanguage, setBaseLanguage] = useState('en-US');
  const [targetLanguages, setTargetLanguages] = useState<string[]>(['ar-SA']);
  const [videoStyle, setVideoStyle] = useState<VideoStyle>('hybrid_presenter_broll');
  const [avatarProvider, setAvatarProvider] = useState('sadtalker');
  const [avatarId, setAvatarId] = useState('default_avatar.png');

  const availableLanguages = [
    { code: 'ar-SA', name: 'Arabic (Saudi Arabia)', flag: '🇸🇦', defaultVoice: 'Hamed Neural (RTL)' },
    { code: 'en-US', name: 'English (United States)', flag: '🇺🇸', defaultVoice: 'Jenny Neural' },
    { code: 'fr-FR', name: 'French (France)', flag: '🇫🇷', defaultVoice: 'Henri Neural' },
    { code: 'de-DE', name: 'German (Germany)', flag: '🇩🇪', defaultVoice: 'Killian Neural' },
    { code: 'ur-PK', name: 'Urdu (Pakistan)', flag: '🇵🇰', defaultVoice: 'Asad Neural (RTL)' },
    { code: 'bn-BD', name: 'Bengali (Bangladesh)', flag: '🇧🇩', defaultVoice: 'Bashkar Neural' },
  ];

  const stylesList: {
    id: VideoStyle;
    title: string;
    description: string;
    badge: string;
  }[] = [
    {
      id: 'hybrid_presenter_broll',
      title: 'Hybrid Presenter + B-Roll (Recommended)',
      description: 'Presenter genuinely leads intro and outro, with dynamic supporting media and motion visuals for core explanations.',
      badge: 'Balanced & Engaging',
    },
    {
      id: 'presenter_led',
      title: 'Presenter-Led',
      description: 'Instructor occupies screen prominently in full or split view, guiding learners directly step by step.',
      badge: 'Instructor Focused',
    },
    {
      id: 'visual_explainer',
      title: 'Visual Explainer',
      description: 'Motion visual sequences, keyphrase overlays, and contextual graphics with voiceover and subtitles.',
      badge: 'Cinematic Graphics',
    },
    {
      id: 'demonstration_tutorial',
      title: 'Demonstration / Tutorial',
      description: 'Action-oriented B-roll and process steps. Ideal for cooking, culinary training, labs, and equipment usage.',
      badge: 'Practical & Procedural',
    },
    {
      id: 'corporate_training',
      title: 'Corporate Training',
      description: 'Professional compliance cards, quiz check, and structured learning objective delivery.',
      badge: 'Enterprise Standard',
    },
  ];

  const toggleLanguage = (code: string) => {
    if (targetLanguages.includes(code)) {
      if (targetLanguages.length > 1) {
        setTargetLanguages(targetLanguages.filter((l) => l !== code));
      }
    } else {
      setTargetLanguages([...targetLanguages, code]);
    }
  };

  const handleCreate = async (mode: 'studio' | 'quick') => {
    if (submitting || isSubmittingRef.current) return;
    isSubmittingRef.current = true;
    try {
      setSubmitting(true);
      setErrorMessage(null);
      setStatusMessage('Initializing project manifest...');

      const payload = serializeCreateProjectRequest({
        topic,
        sourceContent,
        audience,
        baseLanguage,
        targetLanguages,
        duration,
        videoStyle,
        avatarProvider,
        avatarId,
      });

      const manifest = await createProject(payload);
      const projectId = manifest.project_id;

      if (mode === 'quick') {
        setStatusMessage('Starting end-to-end rendering pipeline...');
        // Trigger run pipeline in background
        runPipeline(projectId, false).catch((e) => console.error(e));
        router.push(`/studio/${projectId}/export`);
      } else {
        setStatusMessage('Generating training script...');
        await generateScript(projectId);

        setStatusMessage('Planning storyboard layouts & scenes...');
        await planStoryboard(projectId);

        setStatusMessage('Opening Studio...');
        router.push(`/studio/${projectId}`);
      }
    } catch (err: any) {
      const msg = err?.message || String(err) || 'Failed to create project';
      setErrorMessage(msg);
      setStatusMessage('');
      setSubmitting(false);
      isSubmittingRef.current = false;
    }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Step Indicator Header */}
      <div>
        <Link href="/" className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-cyan-400 mb-4 transition-colors">
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Dashboard</span>
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white">Create Training Video</h1>
            <p className="text-xs sm:text-sm text-slate-400 mt-1">Configure training content, multilingual dubbing, and presenter layout</p>
          </div>
          <span className="text-xs font-mono px-3 py-1 rounded-full bg-slate-800 text-cyan-400 border border-slate-700">
            Step {step} of 5
          </span>
        </div>

        {/* Progress Bar */}
        <div className="w-full h-1.5 bg-slate-800 rounded-full mt-4 overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-cyan-500 to-sky-400 transition-all duration-300"
            style={{ width: `${(step / 5) * 100}%` }}
          />
        </div>
      </div>

      {/* Step Container Card */}
      <div className="rounded-2xl bg-slate-900/80 border border-slate-800 p-6 sm:p-8 shadow-xl">
        {/* STEP 1: Content */}
        {step === 1 && (
          <div className="space-y-6">
            <div className="flex items-center gap-2 pb-2 border-b border-slate-800">
              <BookOpen className="w-5 h-5 text-cyan-400" />
              <h2 className="text-lg font-bold text-white">Training Content & Objectives</h2>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Training Topic <span className="text-cyan-400">*</span>
                </label>
                <input
                  type="text"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g. Workplace Phishing Defense Essentials or Saudi Kabsa Preparation"
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 focus:border-cyan-500 text-sm text-white focus:outline-none transition-colors"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Educational Source Content / Key Notes
                </label>
                <textarea
                  rows={4}
                  value={sourceContent}
                  onChange={(e) => setSourceContent(e.target.value)}
                  placeholder="Outline key learning objectives, steps, safety warnings, or procedure notes..."
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 focus:border-cyan-500 text-sm text-white focus:outline-none transition-colors"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">Target Audience</label>
                  <input
                    type="text"
                    value={audience}
                    onChange={(e) => setAudience(e.target.value)}
                    placeholder="e.g. Kitchen Staff, New Hires, Corporate Employees"
                    className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 focus:border-cyan-500 text-sm text-white focus:outline-none transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                    Desired Duration: <span className="text-cyan-400 font-mono">{duration} seconds</span>
                  </label>
                  <div className="flex items-center gap-3">
                    <input
                      type="range"
                      min={15}
                      max={120}
                      step={5}
                      value={duration}
                      onChange={(e) => setDuration(Number(e.target.value))}
                      className="w-full accent-cyan-400 cursor-pointer"
                    />
                    <div className="flex gap-1.5">
                      {[30, 60].map((preset) => (
                        <button
                          key={preset}
                          type="button"
                          onClick={() => setDuration(preset)}
                          className={`px-2 py-1 rounded text-xs font-mono font-medium ${
                            duration === preset
                              ? 'bg-cyan-500 text-slate-950 font-bold'
                              : 'bg-slate-800 text-slate-300 hover:bg-slate-700'
                          }`}
                        >
                          {preset}s
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STEP 2: Languages */}
        {step === 2 && (
          <div className="space-y-6">
            <div className="flex items-center gap-2 pb-2 border-b border-slate-800">
              <Globe2 className="w-5 h-5 text-cyan-400" />
              <h2 className="text-lg font-bold text-white">Multilingual Localization Control</h2>
            </div>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">Base Canonical Language</label>
                <select
                  value={baseLanguage}
                  onChange={(e) => setBaseLanguage(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-sm text-white focus:outline-none"
                >
                  <option value="en-US">English (United States)</option>
                  <option value="ar-SA">Arabic (Saudi Arabia)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-2">
                  Target Output Languages <span className="text-slate-400">(Select all required versions)</span>
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {availableLanguages.map((lang) => {
                    const isSelected = targetLanguages.includes(lang.code);
                    return (
                      <div
                        key={lang.code}
                        onClick={() => toggleLanguage(lang.code)}
                        className={`p-3.5 rounded-xl border cursor-pointer transition-all flex items-center justify-between ${
                          isSelected
                            ? 'bg-cyan-950/40 border-cyan-500/80 shadow-sm'
                            : 'bg-slate-950/50 border-slate-800 hover:border-slate-700'
                        }`}
                      >
                        <div className="flex items-center gap-3">
                          <span className="text-2xl">{lang.flag}</span>
                          <div>
                            <div className="text-sm font-semibold text-white">{lang.name}</div>
                            <div className="text-xs text-slate-400">{lang.defaultVoice}</div>
                          </div>
                        </div>
                        <div
                          className={`w-5 h-5 rounded-md flex items-center justify-center border ${
                            isSelected ? 'bg-cyan-400 border-cyan-400 text-slate-950' : 'border-slate-700'
                          }`}
                        >
                          {isSelected && <CheckCircle2 className="w-4 h-4 fill-current" />}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STEP 3: Video Style */}
        {step === 3 && (
          <div className="space-y-6">
            <div className="flex items-center gap-2 pb-2 border-b border-slate-800">
              <Palette className="w-5 h-5 text-cyan-400" />
              <h2 className="text-lg font-bold text-white">Select Video Style & Composition</h2>
            </div>

            <div className="grid grid-cols-1 gap-3.5">
              {stylesList.map((st) => {
                const isSelected = videoStyle === st.id;
                return (
                  <div
                    key={st.id}
                    onClick={() => setVideoStyle(st.id)}
                    className={`p-4 rounded-xl border cursor-pointer transition-all flex items-start justify-between gap-4 ${
                      isSelected
                        ? 'bg-cyan-950/50 border-cyan-500 shadow-lg shadow-cyan-500/10'
                        : 'bg-slate-950/40 border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-white">{st.title}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-cyan-300">
                          {st.badge}
                        </span>
                      </div>
                      <p className="text-xs text-slate-400 leading-relaxed">{st.description}</p>
                    </div>
                    <div
                      className={`w-5 h-5 mt-1 rounded-full flex items-center justify-center border ${
                        isSelected ? 'border-cyan-400 bg-cyan-400 text-slate-950' : 'border-slate-700'
                      }`}
                    >
                      {isSelected && <div className="w-2 h-2 rounded-full bg-slate-950" />}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* STEP 4: Presenter Studio */}
        {step === 4 && (
          <div className="space-y-6">
            <div className="flex items-center gap-2 pb-2 border-b border-slate-800">
              <User className="w-5 h-5 text-cyan-400" />
              <h2 className="text-lg font-bold text-white">Presenter & Avatar Studio</h2>
            </div>

            <div className="space-y-4">
              <label className="block text-xs font-semibold text-slate-300">Avatar Generation Engine</label>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div
                  onClick={() => setAvatarProvider('sadtalker')}
                  className={`p-4 rounded-xl border cursor-pointer transition-all ${
                    avatarProvider === 'sadtalker'
                      ? 'bg-cyan-950/50 border-cyan-500'
                      : 'bg-slate-950 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-emerald-400 bg-emerald-950 border border-emerald-800 px-2 py-0.5 rounded">
                      Local GPU • Free
                    </span>
                    <Cpu className="w-4 h-4 text-cyan-400" />
                  </div>
                  <div className="font-bold text-sm text-white">SadTalker Local</div>
                  <p className="text-[11px] text-slate-400 mt-1">Accelerated on NVIDIA RTX 4060 CUDA. Zero API cost.</p>
                </div>

                <div
                  onClick={() => setAvatarProvider('heygen')}
                  className={`p-4 rounded-xl border cursor-pointer transition-all ${
                    avatarProvider === 'heygen'
                      ? 'bg-cyan-950/50 border-cyan-500'
                      : 'bg-slate-950 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-amber-400 bg-amber-950 border border-amber-800 px-2 py-0.5 rounded">
                      Cloud Premium
                    </span>
                    <Wand2 className="w-4 h-4 text-amber-400" />
                  </div>
                  <div className="font-bold text-sm text-white">HeyGen</div>
                  <p className="text-[11px] text-slate-400 mt-1">High-fidelity cloud avatars (Requires API Key).</p>
                </div>

                <div
                  onClick={() => setAvatarProvider('mock')}
                  className={`p-4 rounded-xl border cursor-pointer transition-all ${
                    avatarProvider === 'mock'
                      ? 'bg-cyan-950/50 border-cyan-500'
                      : 'bg-slate-950 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-slate-400 bg-slate-800 px-2 py-0.5 rounded">
                      Fast Mock
                    </span>
                    <Layers className="w-4 h-4 text-slate-400" />
                  </div>
                  <div className="font-bold text-sm text-white">Mock Engine</div>
                  <p className="text-[11px] text-slate-400 mt-1">Instant synthetic rendering for rapid debugging.</p>
                </div>
              </div>

              <div className="pt-2">
                <label className="block text-xs font-semibold text-slate-300 mb-2">Presenter Portrait</label>
                <div
                  onClick={() => setAvatarId('default_avatar.png')}
                  className={`p-4 rounded-xl border flex items-center gap-4 cursor-pointer transition-all ${
                    avatarId === 'default_avatar.png'
                      ? 'bg-cyan-950/40 border-cyan-500'
                      : 'bg-slate-950 border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="w-16 h-16 rounded-xl bg-slate-800 border border-slate-700 flex items-center justify-center overflow-hidden">
                    <User className="w-8 h-8 text-cyan-400" />
                  </div>
                  <div>
                    <div className="text-sm font-bold text-white">Professional Instructor Portrait</div>
                    <div className="text-xs text-slate-400 mt-0.5">assets/avatar_portrait.png (Studio lighting)</div>
                    <div className="text-[11px] text-cyan-400 font-semibold mt-1">Ready for 48kHz audio-driven lipsync</div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* STEP 5: Review & Generate */}
        {step === 5 && (
          <div className="space-y-6">
            <div className="flex items-center gap-2 pb-2 border-b border-slate-800">
              <Sparkles className="w-5 h-5 text-cyan-400" />
              <h2 className="text-lg font-bold text-white">Ready to Generate Storyboard</h2>
            </div>

            <div className="p-4 rounded-xl bg-slate-950 border border-slate-800 space-y-3 text-xs">
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Topic:</span>
                <span className="font-semibold text-white">{topic}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Target Duration:</span>
                <span className="font-mono text-cyan-400 font-bold">{duration} seconds</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Video Style:</span>
                <span className="font-semibold text-white capitalize">{videoStyle.replace(/_/g, ' ')}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Target Locales:</span>
                <span className="font-semibold text-cyan-400">{targetLanguages.join(', ')}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-slate-400">Avatar Engine:</span>
                <span className="font-semibold text-emerald-400 capitalize">{avatarProvider}</span>
              </div>
            </div>

            {errorMessage && (
              <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-800/80 text-rose-200 space-y-2 shadow-lg animate-in fade-in duration-200">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="text-xs font-bold text-rose-200 uppercase tracking-wider flex items-center gap-2">
                      <span>Unable to Create Project</span>
                      <span className="text-[10px] px-1.5 py-0.2 rounded bg-rose-900/80 text-rose-300 font-normal">Validation Error</span>
                    </div>
                    <div className="text-xs font-mono text-rose-300 whitespace-pre-line leading-relaxed bg-black/40 p-2.5 rounded-lg border border-rose-900/40">
                      {errorMessage}
                    </div>
                    <p className="text-[11px] text-rose-300/80">
                      Review your project inputs above or click Back to adjust content and language parameters, then retry.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setErrorMessage(null)}
                    className="text-xs text-rose-400 hover:text-white px-2 py-1 rounded bg-rose-900/40 hover:bg-rose-900 transition-colors"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}

            {submitting ? (
              <div className="p-6 rounded-xl bg-slate-950 border border-slate-800 text-center space-y-3">
                <div className="w-8 h-8 rounded-full border-2 border-cyan-400 border-t-transparent animate-spin mx-auto" />
                <div className="text-sm font-semibold text-white">{statusMessage}</div>
                <p className="text-xs text-slate-400">Running AI storyboard planner and duration targeting...</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                <button
                  type="button"
                  onClick={() => handleCreate('studio')}
                  className="p-4 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 text-left transition-all group"
                >
                  <div className="font-bold text-sm text-white group-hover:text-cyan-400 transition-colors">
                    Studio Mode (Recommended)
                  </div>
                  <p className="text-xs text-slate-400 mt-1">
                    Plan storyboard, inspect scenes, customize media or narration before rendering.
                  </p>
                </button>

                <button
                  type="button"
                  onClick={() => handleCreate('quick')}
                  className="p-4 rounded-xl bg-gradient-to-r from-cyan-500 to-sky-500 hover:from-cyan-400 hover:to-sky-400 text-slate-950 text-left transition-all shadow-lg shadow-cyan-500/20"
                >
                  <div className="font-bold text-sm">Quick Generate & Render</div>
                  <p className="text-xs text-slate-900/80 mt-1">
                    Execute entire end-to-end pipeline automatically and go straight to download.
                  </p>
                </button>
              </div>
            )}
          </div>
        )}

        {/* Navigation Buttons */}
        {!submitting && (
          <div className="flex items-center justify-between pt-6 mt-6 border-t border-slate-800">
            {step > 1 ? (
              <button
                type="button"
                onClick={() => setStep(step - 1)}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 transition-colors"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Back</span>
              </button>
            ) : (
              <div />
            )}

            {step < 5 && (
              <button
                type="button"
                onClick={() => setStep(step + 1)}
                className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl bg-cyan-400 hover:bg-cyan-300 text-slate-950 text-xs font-bold shadow-md transition-all"
              >
                <span>Continue</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
