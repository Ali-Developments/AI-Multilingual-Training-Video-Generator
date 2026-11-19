'use client';

import React, { useMemo, useState } from 'react';
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
  Info,
} from 'lucide-react';
import { createProject, runPipeline, generateScript, planStoryboard } from '@/lib/api';
import { VideoStyle, serializeCreateProjectRequest } from '@/types';

const AVAILABLE_LANGUAGES = [
  { code: 'ar-SA', name: 'Arabic (Saudi Arabia)', flag: '🇸🇦', defaultVoice: 'Hamed Neural (RTL)' },
  { code: 'en-US', name: 'English (United States)', flag: '🇺🇸', defaultVoice: 'Christopher Neural' },
  { code: 'fr-FR', name: 'French (France)', flag: '🇫🇷', defaultVoice: 'Henri Neural' },
  { code: 'de-DE', name: 'German (Germany)', flag: '🇩🇪', defaultVoice: 'Conrad Neural' },
  { code: 'ur-PK', name: 'Urdu (Pakistan)', flag: '🇵🇰', defaultVoice: 'Asad Neural (RTL)' },
  { code: 'bn-BD', name: 'Bengali (Bangladesh)', flag: '🇧🇩', defaultVoice: 'Pradeep Neural' },
];

interface ClientLanguageDetection {
  detectedLocale: string | null;
  detectedName: string | null;
  isMixed: boolean;
  isUncertain: boolean;
}

function detectClientSourceLanguage(topic: string, sourceContent: string): ClientLanguageDetection {
  const combined = `${topic || ''}\n${sourceContent || ''}`.trim();
  const cleaned = combined.replace(/https?:\/\/\S+|[\d\W_]+/g, '');
  if (cleaned.length < 10) {
    return { detectedLocale: null, detectedName: null, isMixed: false, isUncertain: true };
  }

  let latin = 0;
  let arabic = 0;
  let bengali = 0;
  for (const ch of cleaned) {
    const cp = ch.codePointAt(0) || 0;
    if ((cp >= 0x0041 && cp <= 0x005a) || (cp >= 0x0061 && cp <= 0x007a) || (cp >= 0x00c0 && cp <= 0x024f)) {
      latin++;
    } else if (
      (cp >= 0x0600 && cp <= 0x06ff) ||
      (cp >= 0x0750 && cp <= 0x077f) ||
      (cp >= 0x08a0 && cp <= 0x08ff)
    ) {
      arabic++;
    } else if (cp >= 0x0980 && cp <= 0x09ff) {
      bengali++;
    }
  }

  const total = latin + arabic + bengali;
  if (total < 6) {
    return { detectedLocale: null, detectedName: null, isMixed: false, isUncertain: true };
  }

  const ratios = { latin: latin / total, arabic: arabic / total, bengali: bengali / total };
  const activeScripts = Object.entries(ratios).filter(([, r]) => r >= 0.15);
  const isMixed = activeScripts.length >= 2;

  if (ratios.bengali >= 0.35) {
    return {
      detectedLocale: 'bn-BD',
      detectedName: 'Bengali (Bangladesh)',
      isMixed,
      isUncertain: false,
    };
  }

  if (ratios.arabic >= 0.35) {
    const urduChars = (combined.match(/[ٹڈڑںےہھپچژگک]/g) || []).length;
    const urduWords = (combined.match(/\b(کے|میں|کی|ہے|اور|کو|سے|پر|کا|ہیں|لیے|کریں)\b/g) || []).length;
    const arabicWords = (combined.match(/\b(في|من|على|إلى|عن|هذا|هذه|التي|الذي|مع|أو|أن|كل|عند)\b/g) || []).length;
    if (urduChars * 1.5 + urduWords * 2.5 > arabicWords * 2.5 + 1.5) {
      return {
        detectedLocale: 'ur-PK',
        detectedName: 'Urdu (Pakistan)',
        isMixed,
        isUncertain: false,
      };
    }
    return {
      detectedLocale: 'ar-SA',
      detectedName: 'Arabic (Saudi Arabia)',
      isMixed,
      isUncertain: false,
    };
  }

  if (ratios.latin >= 0.4) {
    const lower = combined.toLowerCase();
    const frHits = (lower.match(/\b(le|la|les|des|une|dans|pour|avec|sur|pas|plus|vous|cette|aux|être|faire|du|au|et|est)\b/g) || []).length +
      (lower.match(/[éèêëàâçùûîïôœ]/g) || []).length;
    const deHits = (lower.match(/\b(der|die|das|und|den|von|zu|mit|sich|auf|für|nicht|ist|dem|ein|eine|werden|aus|sind|oder|wir)\b/g) || []).length +
      (lower.match(/[äöüß]/g) || []).length * 1.5;
    const enHits = (lower.match(/\b(the|and|for|with|from|that|this|are|you|your|always|never|check|how|into|when|before|after|should|must|in|to|of)\b/g) || []).length;

    if (frHits >= 2 && frHits > enHits * 1.2 && frHits > deHits * 1.2) {
      return { detectedLocale: 'fr-FR', detectedName: 'French (France)', isMixed, isUncertain: false };
    }
    if (deHits >= 2 && deHits > enHits * 1.2 && deHits > frHits * 1.2) {
      return { detectedLocale: 'de-DE', detectedName: 'German (Germany)', isMixed, isUncertain: false };
    }
    if (enHits >= 1) {
      return { detectedLocale: 'en-US', detectedName: 'English (United States)', isMixed, isUncertain: false };
    }
  }

  return { detectedLocale: null, detectedName: null, isMixed, isUncertain: true };
}

export default function CreateVideoWizard() {
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const isSubmittingRef = React.useRef(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [failedStage, setFailedStage] = useState<'create' | 'script' | 'storyboard' | null>(null);
  const [createdProjectId, setCreatedProjectId] = useState<string | null>(null);

  // Form State — starts clean so default English sample text never overrides Arabic or multilingual topics
  const [topic, setTopic] = useState('');
  const [sourceContent, setSourceContent] = useState('');
  const [audience, setAudience] = useState('General Professional / Adult Learner');
  const [duration, setDuration] = useState(30);
  const [sourceLanguage, setSourceLanguage] = useState<string>('auto');
  const [baseLanguage, setBaseLanguage] = useState<string>('ar-SA');
  const [targetLanguages, setTargetLanguages] = useState<string[]>(['ar-SA']);
  const [videoStyle, setVideoStyle] = useState<VideoStyle>('hybrid_presenter_broll');
  const [avatarProvider, setAvatarProvider] = useState('sadtalker');
  const [avatarId, setAvatarId] = useState('default_avatar.png');

  const detection = useMemo(
    () => detectClientSourceLanguage(topic, sourceContent),
    [topic, sourceContent]
  );

  const resolvedSourceLocale =
    sourceLanguage !== 'auto' ? sourceLanguage : detection.detectedLocale;

  const getLanguageName = (code: string | null) => {
    if (!code) return 'Auto-Detected';
    return AVAILABLE_LANGUAGES.find((l) => l.code === code)?.name || code;
  };

  const languageMismatchAdvisory = useMemo(() => {
    const canonPrefix = baseLanguage.split('-')[0].toLowerCase();
    const canonName = getLanguageName(baseLanguage);

    if (detection.isMixed) {
      return `Mixed-language source material detected. The master canonical script will be unified and written in ${canonName} (${baseLanguage}).`;
    }
    if (resolvedSourceLocale) {
      const srcPrefix = resolvedSourceLocale.split('-')[0].toLowerCase();
      if (srcPrefix !== canonPrefix) {
        const srcName = getLanguageName(resolvedSourceLocale);
        return `Source material is in ${srcName} (${resolvedSourceLocale}), while Canonical Script Language is set to ${canonName} (${baseLanguage}). The studio will automatically translate and author the master script in ${canonName}.`;
      }
    }
    return null;
  }, [baseLanguage, detection.isMixed, resolvedSourceLocale]);

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

  const applySampleTemplate = (preset: 'bechamel_en_to_ar' | 'kabsa_ar' | 'phishing_en') => {
    setErrorMessage(null);
    if (preset === 'bechamel_en_to_ar') {
      setTopic('Egyptian Macaroni Béchamel Preparation');
      setSourceContent(
        'Boil penne pasta until al dente. Brown minced beef with onions, garlic, salt, black pepper, and cinnamon. Prepare creamy béchamel sauce by whisking butter, flour, and warm milk until smooth, then layer pasta, spiced meat, and béchamel and bake until golden brown.'
      );
      setAudience('Home Cooks & Culinary Students');
      setSourceLanguage('auto');
      setBaseLanguage('ar-SA');
      setTargetLanguages(['ar-SA']);
      setVideoStyle('demonstration_tutorial');
    } else if (preset === 'kabsa_ar') {
      setTopic('طريقة تحضير الكبسة السعودية الأصيلة');
      setSourceContent(
        'تشويح البصل والطماطم مع البهارات الصحيحة مثل الهيل والقرفة والقرنفل واللومي، ثم إضافة الدجاج والمرق وطهي أرز البسمتي على نار هادئة وتقديمه مع اللوز المحمص.'
      );
      setAudience('الطهاة المبتدئون وعشاق المطبخ العربي');
      setSourceLanguage('auto');
      setBaseLanguage('ar-SA');
      setTargetLanguages(['ar-SA', 'en-US']);
      setVideoStyle('demonstration_tutorial');
    } else {
      setTopic('Workplace Phishing Defense Essentials');
      setSourceContent(
        'Identify suspicious emails, check sender domain names, never click unexpected attachments or links, and report threats immediately to cybersecurity operations.'
      );
      setAudience('Corporate Employees & Staff');
      setSourceLanguage('auto');
      setBaseLanguage('en-US');
      setTargetLanguages(['ar-SA']);
      setVideoStyle('hybrid_presenter_broll');
    }
  };

  const handleNextStep = () => {
    if (step === 1 && !topic.trim() && !sourceContent.trim()) {
      setErrorMessage('Please enter a Training Topic or Source Content before continuing.');
      return;
    }
    setErrorMessage(null);
    setStep(step + 1);
  };

  const handleCreate = async (mode: 'studio' | 'quick') => {
    if (submitting || isSubmittingRef.current) return;
    if (!topic.trim() && !sourceContent.trim()) {
      setErrorMessage('Please provide at least a Training Topic or Educational Source Content.');
      return;
    }
    isSubmittingRef.current = true;
    let currentStage: 'create' | 'script' | 'storyboard' = 'create';
    try {
      setSubmitting(true);
      setErrorMessage(null);
      setFailedStage(null);

      let projectId = createdProjectId;
      if (!projectId) {
        setStatusMessage('Initializing project manifest...');
        const payload = serializeCreateProjectRequest({
          topic,
          sourceContent,
          audience,
          sourceLanguage,
          baseLanguage,
          canonicalLanguage: baseLanguage,
          targetLanguages,
          duration,
          videoStyle,
          avatarProvider,
          avatarId,
        });

        const manifest = await createProject(payload);
        projectId = manifest.project_id;
        setCreatedProjectId(projectId);
      }

      if (mode === 'quick') {
        setStatusMessage('Starting end-to-end rendering pipeline...');
        runPipeline(projectId, false).catch((e) => console.error(e));
        router.push(`/studio/${projectId}/export`);
      } else {
        currentStage = 'script';
        setStatusMessage('Generating training script...');
        await generateScript(projectId);

        currentStage = 'storyboard';
        setStatusMessage('Planning storyboard layouts & scenes...');
        await planStoryboard(projectId);

        setStatusMessage('Opening Studio...');
        router.push(`/studio/${projectId}`);
      }
    } catch (err: any) {
      const msg = err?.message || String(err) || 'Failed to create project';
      setFailedStage(currentStage);
      setErrorMessage(msg);
      setStatusMessage('');
      setSubmitting(false);
      isSubmittingRef.current = false;
    }
  };

  if (process.env.NEXT_PUBLIC_LOCAL_LESSON_URL) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-8 space-y-4">
        <h1 className="text-2xl font-extrabold text-white">Create a local training video</h1>
        <p className="text-sm text-slate-300">Import your narration and matching transcript, then render the presenter in Studio.</p>
        <a href={process.env.NEXT_PUBLIC_LOCAL_LESSON_URL} className="inline-flex rounded-lg bg-cyan-400 px-4 py-2 font-semibold text-slate-950">
          Import a WAV recording
        </a>
      </div>
    );
  }

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
            <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-slate-800">
              <div className="flex items-center gap-2">
                <BookOpen className="w-5 h-5 text-cyan-400" />
                <h2 className="text-lg font-bold text-white">Training Content & Objectives</h2>
              </div>
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] text-slate-400 mr-1">Quick Templates:</span>
                <button
                  type="button"
                  onClick={() => applySampleTemplate('bechamel_en_to_ar')}
                  className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700 transition-colors"
                >
                  EN → AR Béchamel
                </button>
                <button
                  type="button"
                  onClick={() => applySampleTemplate('kabsa_ar')}
                  className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-cyan-300 border border-slate-700 transition-colors"
                >
                  AR → EN/AR Kabsa
                </button>
                <button
                  type="button"
                  onClick={() => applySampleTemplate('phishing_en')}
                  className="text-[11px] px-2.5 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors"
                >
                  Phishing Security
                </button>
              </div>
            </div>

            {errorMessage && (
              <div className="p-3 rounded-xl bg-rose-950/60 border border-rose-800/80 text-xs text-rose-200 flex items-center gap-2">
                <AlertCircle className="w-4 h-4 text-rose-400 shrink-0" />
                <span>{errorMessage}</span>
              </div>
            )}

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Training Topic <span className="text-cyan-400">*</span>
                </label>
                <input
                  type="text"
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="Enter topic in any supported language (e.g., Egyptian Macaroni Béchamel or طريقة عمل المكرونة بالبشاميل)"
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 focus:border-cyan-500 text-sm text-white focus:outline-none transition-colors"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="block text-xs font-semibold text-slate-300">
                    Educational Source Content / Key Notes <span className="text-slate-500 font-normal">(Optional if Topic is provided)</span>
                  </label>
                  {detection.detectedName && (
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-cyan-950/60 text-cyan-300 border border-cyan-800/60">
                      Detected Input: {detection.isMixed ? `Mixed (${detection.detectedName})` : detection.detectedName}
                    </span>
                  )}
                </div>
                <textarea
                  rows={4}
                  value={sourceContent}
                  onChange={(e) => setSourceContent(e.target.value)}
                  placeholder="Paste source instructions, recipe steps, outline, or mixed-language notes in Arabic, English, French, German, Urdu, or Bengali..."
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
                    placeholder="e.g. Home Cooks, Kitchen Staff, New Hires, Corporate Employees"
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

            <div className="space-y-5">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* 1. Source Material Language */}
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Source Material Language
                  </label>
                  <p className="text-[11px] text-slate-400 mb-2">
                    Language of your input topic and notes from Step 1
                  </p>
                  <select
                    value={sourceLanguage}
                    onChange={(e) => setSourceLanguage(e.target.value)}
                    className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-sm text-white focus:outline-none focus:border-cyan-500"
                  >
                    <option value="auto">
                      Auto Detect (Recommended){detection.detectedName ? ` — ${detection.detectedName}` : ''}
                    </option>
                    {AVAILABLE_LANGUAGES.map((lang) => (
                      <option key={`src-${lang.code}`} value={lang.code}>
                        {lang.flag} {lang.name}
                      </option>
                    ))}
                  </select>
                </div>

                {/* 2. Canonical Script Language */}
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">
                    Canonical Script Language
                  </label>
                  <p className="text-[11px] text-slate-400 mb-2">
                    Primary language in which the master storyboard script is authored
                  </p>
                  <select
                    value={baseLanguage}
                    onChange={(e) => {
                      const nextBase = e.target.value;
                      setBaseLanguage(nextBase);
                      if (targetLanguages.length === 0) {
                        setTargetLanguages([nextBase]);
                      }
                    }}
                    className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-800 text-sm text-white focus:outline-none focus:border-cyan-500"
                  >
                    {AVAILABLE_LANGUAGES.map((lang) => (
                      <option key={`canon-${lang.code}`} value={lang.code}>
                        {lang.flag} {lang.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Non-blocking Cross-Language Advisory */}
              {languageMismatchAdvisory && (
                <div className="p-3.5 rounded-xl bg-amber-950/40 border border-amber-700/60 text-amber-200 text-xs flex items-start gap-3">
                  <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <div className="font-semibold text-amber-300">Cross-Language Script Generation (Non-Blocking)</div>
                    <p className="text-amber-200/90 leading-relaxed">{languageMismatchAdvisory}</p>
                  </div>
                </div>
              )}

              {/* 3. Target Output Languages */}
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-2">
                  Target Output Video Languages <span className="text-slate-400">(Select all required video versions)</span>
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {AVAILABLE_LANGUAGES.map((lang) => {
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
                <span className="font-semibold text-white">{topic || '(Derived from Source Notes)'}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Source Material Language:</span>
                <span className="font-semibold text-slate-200">
                  {sourceLanguage === 'auto'
                    ? `Auto-Detected (${detection.detectedName || 'Automatic'})`
                    : getLanguageName(sourceLanguage)}
                </span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Canonical Script Language:</span>
                <span className="font-semibold text-cyan-400">{getLanguageName(baseLanguage)} ({baseLanguage})</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Target Output Locales:</span>
                <span className="font-semibold text-cyan-400">{targetLanguages.join(', ')}</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Target Duration:</span>
                <span className="font-mono text-cyan-400 font-bold">{duration} seconds</span>
              </div>
              <div className="flex justify-between py-1 border-b border-slate-800/80">
                <span className="text-slate-400">Video Style:</span>
                <span className="font-semibold text-white capitalize">{videoStyle.replace(/_/g, ' ')}</span>
              </div>
              <div className="flex justify-between py-1">
                <span className="text-slate-400">Avatar Engine:</span>
                <span className="font-semibold text-emerald-400 capitalize">{avatarProvider}</span>
              </div>
            </div>

            {languageMismatchAdvisory && (
              <div className="p-3.5 rounded-xl bg-amber-950/40 border border-amber-700/60 text-amber-200 text-xs flex items-start gap-3">
                <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
                <div>{languageMismatchAdvisory}</div>
              </div>
            )}

            {errorMessage && (
              <div className="p-4 rounded-xl bg-rose-950/60 border border-rose-800/80 text-rose-200 space-y-2 shadow-lg animate-in fade-in duration-200">
                <div className="flex items-start gap-3">
                  <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
                  <div className="space-y-1.5 flex-1 min-w-0">
                    <div className="text-xs font-bold text-rose-200 uppercase tracking-wider flex items-center gap-2">
                      <span>
                        {failedStage === 'script'
                          ? 'Script Generation Failed'
                          : failedStage === 'storyboard'
                          ? 'Storyboard Planning Failed'
                          : 'Unable to Create Project'}
                      </span>
                      <span className="text-[10px] px-1.5 py-0.2 rounded bg-rose-900/80 text-rose-300 font-normal">
                        {failedStage === 'script' ? 'LLM / Script Error' : 'Validation / Server Error'}
                      </span>
                    </div>
                    <div className="text-xs font-mono text-rose-300 whitespace-pre-line leading-relaxed bg-black/40 p-2.5 rounded-lg border border-rose-900/40">
                      {errorMessage}
                    </div>
                    <p className="text-[11px] text-rose-300/80">
                      {createdProjectId
                        ? `Retry Studio Mode to continue project ${createdProjectId} using its saved inputs.`
                        : 'Review the project inputs and retry.'}
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
                onClick={() => {
                  setErrorMessage(null);
                  setStep(step - 1);
                }}
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
                onClick={handleNextStep}
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
