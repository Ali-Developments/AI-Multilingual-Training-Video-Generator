# AI Multilingual Training Video Generation Platform — Studio V2

> **Project Classification:** Autonomous Multi-Modal Educational Video Studio & Generation Platform  
> **Status:** VIDEO STUDIO V2 OPERATIONAL — PRESENTER-LED ARCHITECTURE & NEXT.JS STUDIO (October 2026)  
> **Maintainer:** Ali Mostafa ([Ali-Developments](https://github.com/Ali-Developments))  
> **Key Architecture Documents:**
> - [VIDEO_STUDIO_V2_ARCHITECTURE.md](VIDEO_STUDIO_V2_ARCHITECTURE.md)
> - [VIDEO_STUDIO_V2_FRONTEND.md](VIDEO_STUDIO_V2_FRONTEND.md)
> - [SCENE_MEDIA_ARCHITECTURE.md](SCENE_MEDIA_ARCHITECTURE.md)
> - [VIDEO_STUDIO_V2_ACCEPTANCE_REPORT.md](VIDEO_STUDIO_V2_ACCEPTANCE_REPORT.md)

An enterprise-grade autonomous studio designed to transform curriculum texts and educational outlines into composed, localized training video packages with talking-head presenters, supporting graphics, motion visuals, and subtitles.

---

## 🎯 Studio V2 Highlights

1. **Professional Next.js 14 Web Studio (`web/`):** Dedicated App Router interface replacing Streamlit as the primary production dashboard. Features 5-step Project Wizard, 3-column Scene Studio with live HTML5 player & subtitle safe zone, interactive timeline strip, and delivery dashboard.
2. **Presenter-Led Composition Engine:** Replaces legacy slide cards with natural video layouts:
   - `presenter_split`: 42% presenter width on dark studio canvas paired with 58% contextual media.
   - `presenter_full`: Centered 960×960 framed avatar on studio slate with dedicated lower-third subtitles.
   - `media_full` & `media_with_overlay`: Full-bleed cinematic B-roll with contextual keyphrases.
3. **Local Motion Visual Engine:** Free, local Ken Burns pan/zoom generation using FFmpeg (`zoompan` filter) turning concepts into dynamic B-roll.
4. **AI Storyboard Planning:** Automatic intelligent allocation of presenter vs. B-roll vs. quiz vs. outro scenes based on selected video style (`hybrid_presenter_broll`, `demonstration_tutorial`, etc.).
5. **Zero Developer Metadata:** Complete elimination of internal developer and slide markers (`SCENE 4`, `OUTRO`, `OBJECTIVE`, `Content delivery`) from production video.
6. **Subprocess-Isolated SadTalker on CUDA:** High-resolution local avatar rendering on NVIDIA RTX 4060 GPU without API credits.
7. **Legacy / Debug UI:** Streamlit preserved strictly for diagnostic/developer debugging at `frontend/streamlit_app.py`.

The platform converts training topics or raw curriculum materials into localized, multi-asset video packages comprising:

1. **Deterministic Canonical Scripting:** LangGraph StateGraph workflow with structured pedagogical analysis, scene structuring, and quality validation.
2. **Linguistic & Cultural Localization:** Multilingual adaptation for Saudi Arabic (`ar-SA` with Right-to-Left RTL metadata) and Bengali (`bn-BD` with Left-to-Right LTR metadata), preserving learning objectives and domain terminology.
3. **Voiceover Synthesis & Timing Synchronization:** Multi-provider TTS (Edge-TTS free WebSocket tier) with measured waveform durations serving as timing ground truth.
4. **Post-TTS Duration Reconciliation:** Dedicated `DurationReconciliationService` reconciling real audio duration with target limits via proportional scene budgeting and LLM condensation.
5. **Free Local Talking-Head Avatar:** Subprocess-isolated SadTalker engine running locally on CUDA GPU without API credits, animating a high-resolution presenter portrait in PiP format.
6. **Full HD Supporting Visual Slides:** Local Pillow 1920x1080 graphic card rendering adapted to scene instructional roles (intro, visual demo, explanation, recap, outro).
7. **Complex RTL Subtitle Generation:** Advanced SubStation Alpha (`.ass`) with libass and HarfBuzz complex shaping, alongside `.srt` and `.vtt`.
8. **Native FFmpeg Video Composition:** Automated multi-track composition layering presenter video in Picture-in-Picture (PiP), visual slides, audio normalized to 48,000 Hz stereo AAC, and subtitles into standard 1920x1080 MP4 files.
9. **Project Manifest & Resume Engine:** Persistent `project.json` manifest with stage idempotency and partial pipeline resume capabilities.
10. **Dual Access Interface:** FastAPI REST API (`/api/v1/projects`) and an interactive Streamlit Studio dashboard.

---

## 🏗️ Architecture & Pipeline Flow

`	ext
Training Video Request (Topic / Locales / Target Duration)
                           │
                           ▼
            LangGraph Canonical Script Workflow
      (normalize -> analyze -> generate -> validate -> finalize)
                           │
                           ▼
         Multilingual Localization Service
    (ar-SA [RTL], cultural & terminology adaptation)
                           │
                           ▼
              Speech Synthesis (Edge-TTS)
       (authoritative waveform duration via ffprobe)
                           │
                           ▼
         Post-TTS Duration Reconciliation Service
     (overrun detection -> scene budgets -> condensation)
                           │
                           ▼
                 Duration Approval Gate
                           │
          ┌────────────────┴────────────────┐
          ▼                                 ▼
SadTalker Local Avatar Engine      Full HD Supporting Visuals
(CUDA-accelerated presenter PiP)  (Pillow 1920x1080 slide cards)
          └────────────────┬────────────────┘
                           ▼
          Deterministic Subtitle Engine (.ass / .srt / .vtt)
              (complex HarfBuzz RTL Arabic shaping)
                           │
                           ▼
             FFmpeg Composition Engine
   (48kHz stereo AAC normalization + scene concatenation)
                           │
                           ▼
      Final Composed Training Videos (1920x1080 MP4)
               (e.g., training_ar-SA.mp4)
`

---

## 📂 Repository Structure

```text
Video-Automation/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── health.py            # Service health probe endpoint
│   │       └── projects.py          # Project lifecycle REST endpoints
│   ├── core/
│   │   ├── config.py                # Pydantic Settings & environment variables
│   │   ├── exceptions.py            # Unified domain exception hierarchy
│   │   └── logging.py               # Structured application logging
│   ├── models/
│   │   └── schemas.py               # Complete Pydantic schemas and contracts
│   ├── services/
│   │   ├── avatar/                  # AvatarProvider, HeyGenProvider, MockAvatarProvider
│   │   ├── composition/             # CompositionProvider, FFmpegCompositionProvider
│   │   ├── llm/                     # LLMProvider, GroqProvider, MockLLMProvider
│   │   ├── localization/            # LocalizationService, cultural adaptation, validators
│   │   ├── subtitles/               # SubtitleProvider, DeterministicSubtitleProvider
│   │   ├── tts/                     # TTSProvider, EdgeTTSProvider, MockTTSProvider, audio_probe
│   │   └── visuals/                 # VisualAssetProvider, LocalVisualProvider
│   ├── workflows/
│   │   ├── script_generation/       # LangGraph script generation state graph
│   │   ├── manifest.py              # ProjectManifestManager (atomic project.json persistence)
│   │   └── orchestrator.py          # ProjectOrchestrator (full pipeline coordinator)
│   └── main.py                      # FastAPI application entrypoint
├── docs/
│   └── screenshots/                 # Application screenshots placeholder (.gitkeep)
├── frontend/
│   ├── helpers.py                   # API client, error handling, and serialization helpers
│   └── streamlit_app.py             # Streamlit Studio interactive dashboard
├── storage/
│   └── projects/                    # File-based project storage (<project_id>/)
├── tests/                           # 255 automated regression and integration tests
├── .env.example                     # Environment configuration template
├── requirements.txt                 # Python dependencies
├── ARCHITECTURE.md                  # Detailed technical architecture specification
├── DEVELOPMENT.md                   # Developer guide and testing protocols
├── AUTONOMOUS_PROGRESS.md           # Progress and milestone execution log
├── PROJECT_AUDIT_AND_TECHNICAL_REPORT.md  # Formal engineering audit report
└── PROJECT_AUDIT_AND_TECHNICAL_REPORT.pdf # Executive PDF audit report
```

---

## 🚀 Quickstart Guide

### 1. Prerequisites
- **Python:** 3.10 to 3.13 (Tested on Python 3.13.5).
- **FFmpeg & ffprobe:** Must be installed and accessible on system `PATH`.
  ```powershell
  ffmpeg -version
  ffprobe -version
  ```

### 2. Environment Setup
```powershell
# Clone the repository
git clone https://github.com/Ali-Developments/AI-Multilingual-Training-Video-Generator.git
cd AI-Multilingual-Training-Video-Generator

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # On Windows
# source .venv/bin/activate  # On Linux/macOS

# Install dependencies
python -m pip install -r requirements.txt
```

### 3. Configuration
Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```
Default configuration runs in **Mock Mode** for avatars (`DEFAULT_AVATAR_PROVIDER=mock`) and **Edge-TTS** (free native WebSocket voice synthesis), requiring zero paid API keys to run.

To configure live Groq LLM:
```env
DEFAULT_LLM_PROVIDER=groq
GROQ_API_KEY=your_groq_api_key_here
GROQ_MODEL=openai/gpt-oss-20b
```

### 4. Running the Backend API
```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- OpenAPI / Swagger UI: `http://localhost:8000/docs`
- Service Health Check: `http://localhost:8000/api/v1/health`
- Projects REST API: `http://localhost:8000/api/v1/projects`

### 5. Running the Streamlit Studio
```powershell
python -m streamlit run frontend/streamlit_app.py
```
Open `http://localhost:8501` to:
- Configure training topics, target audience, and target locales (`ar-SA`, `bn-BD`, etc.).
- Inspect canonical English scripts alongside RTL Arabic and Bengali localized scripts.
- Listen to synthesized audio tracks.
- Preview avatar video segments and generated Full HD visual slide cards.
- View and download subtitle files (`.srt`, `.vtt`).
- Play and download final composed training videos (`.mp4`).

### 6. Running Automated Tests
```powershell
python -m pytest -v
```
- **162 passing tests** (100% pass rate).
- All tests execute strictly against mock providers consuming **$0.00** in API credits.

---

## 📸 Screenshots & UI Showcase

Screenshots are organized in [`docs/screenshots/`](docs/screenshots/):
- **Dashboard & Project Creation:** Configure curriculum topic, target duration, tone, and multilingual locales.
- **Script & Localization Inspector:** Side-by-side script review with RTL cultural guidance notes.
- **Audio & Presenter Playback:** Per-scene waveform audio player and avatar segments.
- **Visuals & Subtitles:** Full HD 1080p slide card previews and cue timings.
- **Final Composed Videos:** Composed multilingual training video player.
- **Diagnostics & Manifest:** Live stage-by-stage status and error inspection.

---

## 🔍 Verified Real vs. Mock Status

| Provider Subsystem | Implementation | Mock Tested | Locally Tested | External Live Tested | Operational Status |
|---|---|:---:|:---:|:---:|---|
| **LLM (Groq)** | `GroqProvider` | YES | YES | PARTIAL | Functional (Subject to external rate limits) |
| **TTS (Edge-TTS)**| `EdgeTTSProvider` | YES | YES | YES | Functional (Free native WebSocket tier) |
| **Avatar (HeyGen)**| `HeyGenProvider` | YES | NO | NO | **Guarded in Mock Mode (0 Credits Used)** |
| **Visuals (Pillow)**| `PillowVisualProvider` | YES | YES | N/A | Fully Functional (Deterministic local 1080p rendering) |
| **Subtitles** | `DeterministicSubtitleEngine` | YES | YES | N/A | Fully Functional (Calculated from audio probe) |
| **Composition** | `FFmpegCompositionProvider` | YES | YES | N/A | Fully Functional (Requires local FFmpeg binary) |

---

## ⚠️ Known Platform Limitations & Audit Notes

For the full detailed defect register and root-cause analyses, refer to [PROJECT_AUDIT_AND_TECHNICAL_REPORT.md](PROJECT_AUDIT_AND_TECHNICAL_REPORT.md). Key findings include:

1. **Pre-TTS Speech Duration Estimation:** The space-separated WPM calculation in `validators.py` underestimates spoken Arabic duration, which can trigger duration validation failures on short video requests ($< 45$ seconds).
2. **Diagnostic Error Surfacing:** In the script generation workflow, `orchestrator.py` queries `state.get('error_message')` instead of `state.errors`, masking specific validation issues behind the generic message `"Script generation failed: No final script produced"`.
3. **HeyGen Avatar Live Execution:** Live avatar rendering is not enabled by default (`DEFAULT_AVATAR_PROVIDER=mock`) and has not been live-validated in production to protect user billing.
4. **Single-Node File Storage:** Project manifests and media artifacts reside on local filesystem storage (`storage/projects/`) without database locking.

---

## 🛡️ Cost-Safety & Security Principles

- **Cost-Safety Guard:** `ENABLE_LIVE_API_TESTS=False` prevents unexpected charges during testing or local development.
- **Strict Decoupling:** Every external capability (LLM, TTS, Avatar, Composition, Visuals) resides behind an abstract interface.
- **Path Traversal Defense:** Project IDs are sanitized and strictly confined to `storage/projects/`.
- **Zero Secrets Tracked:** No API keys are written to disk, exposed in manifests, or committed to Git.

---

## 📄 License & Attribution

Developed by [Ali Mostafa](https://github.com/Ali-Developments). Educational and research prototype for automated multilingual media generation.
