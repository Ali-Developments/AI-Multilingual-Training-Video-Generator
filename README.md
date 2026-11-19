# AI Multilingual Training Video Studio

> **An end-to-end AI engineering platform for generating, localizing, editing, and rendering multilingual training videos — combining staged LLM script generation with crash-safe checkpoint/resume, neural text-to-speech, local CUDA talking avatars, Arabic RTL subtitles, and native FFmpeg 1080p composition.**

[![Python](https://img.shields.io/badge/Python-3.10%20--%203.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-14.2%20App%20Router-black?logo=next.js&logoColor=white)](https://nextjs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind-3.4+-06B6D4?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![OpenRouter](https://img.shields.io/badge/LLM-OpenRouter%20%7C%20Groq-6366F1)](https://openrouter.ai/)
[![Edge-TTS](https://img.shields.io/badge/TTS-Edge--TTS%20Neural-0078D7)](https://github.com/rany2/edge-tts)
[![SadTalker](https://img.shields.io/badge/Avatar-SadTalker%20(Local%20CUDA)-7952B3)](https://github.com/OpenTalker/SadTalker)
[![FFmpeg](https://img.shields.io/badge/Composition-FFmpeg%207.0+-007808?logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

---

## 1. Project Overview

**AI Multilingual Training Video Studio** automates the creation of structured instructional videos from raw text, curriculum outlines, or procedural instructions (such as English source instructions rendered into an Arabic training video). It pairs a **FastAPI + LangGraph Python backend** with a **Next.js 14 App Router Studio UI**, enabling both interactive scene-by-scene editing (**Studio Mode**) and full pipeline orchestration (**Quick Generate & Render**).

The platform is engineered around **zero-cost local execution by default**:
- **OpenRouter Free Tier (`openrouter/free`)** with fail-closed paid-model guards for script generation (with optional Groq support behind an explicit authorization flag).
- **Edge-TTS** for free multilingual neural narration.
- **Local SadTalker (CUDA)** for talking-head presenter synthesis (with `MockAvatarProvider` for instant offline testing and optional gated HeyGen support).
- **Native FFmpeg** for 1080p H.264/AAC multi-track composition and HarfBuzz/libass Arabic RTL subtitle rendering.

---

## 2. Problem Statement

Producing localized corporate or technical training videos across languages (especially Right-to-Left languages like Arabic) presents four recurring engineering challenges:

1. **Production Overhead**: Traditional multi-language video workflows require separate scriptwriters, translators, voice actors, presenters, and manual video editors for every locale.
2. **Unreliable Free/Small LLM Structured Output**: Generating a full multi-scene `ScriptDraft` JSON payload in a single prompt frequently fails on free or reasoning-heavy LLMs due to `max_tokens` truncation, reasoning-only responses, schema echoing (`$defs`), or variable free-router latency.
3. **Expensive Partial Failures**: Without durable checkpoints, OS-level locking, and request accounting, a timeout or crash on scene 4 of 6 wastes previously accepted LLM work and risks duplicate spending or concurrent corruption.
4. **Multilingual & RTL Rendering Fragility**: Arabic narration has different speech-rate pacing (~115 WPM vs. ~140 WPM for English) and requires proper Bidirectional/HarfBuzz glyph shaping in burned-in subtitles to avoid disconnected or reversed characters.

---

## 3. Main Objectives

- Accept source material in any supported language (or mixed Arabic/English) and generate canonical scripts and localized videos in user-selected target locales without false blocking.
- Make multi-scene script generation resilient on free-tier LLMs through **staged generation** (`ContentAnalysis → ScriptOutline → SceneDraft[1..N] → ScriptDraft`) and **crash-safe checkpoint/resume**.
- Enforce **fail-closed cost and concurrency controls** (OS-backed per-project locks, durable request ledgers, explicit paid-model gates).
- Provide an interactive **Video Studio v2** frontend for reviewing scripts, editing scenes, uploading custom media, previewing layouts, and exporting 1080p MP4 deliverables.

---

## 4. Key Features & Implementation Status

The table below distinguishes **implemented and offline-tested** capabilities from **not live-verified**, **experimental**, and **planned** features:

| Subsystem | Description | Implementation Status |
| :--- | :--- | :--- |
| **Staged Script Generation** | `ContentAnalysis → ScriptOutline → Sequential SceneDrafts → Assembly & Validation → Targeted Scene Repair` via LangGraph | **Implemented & Offline-Tested** *(live `openrouter/free` completion subject to upstream free-router latency)* |
| **Script Checkpoint & Resume** | Checksummed v2 JSON checkpoints, complete generation identity fingerprinting, predecessor lineage tracking, and repair-task persistence | **Implemented & Offline-Tested** *(verified with real multi-process crash/restart tests)* |
| **OS-Backed Locking & Request Ledger** | Per-project `msvcrt.locking` / `fcntl.flock` exclusive locks (`.script.lock`, `.manifest.lock`, `.script_requests.lock`) + durable `script_requests.json` reservation ledger | **Implemented & Offline-Tested** *(single-machine local filesystem scope)* |
| **OpenRouter Provider & Decompression Fix** | Streaming HTTPX transport with single-pass automatic decompression, `OpenRouterDecodingError` classification, wall-clock watchdog, `RunControl` timeout/cancellation separation, and fail-closed paid-model gate | **Implemented & Offline-Tested** *(decompression & cancellation fixes verified offline; full 6-scene live run pending manual verification)* |
| **Multilingual Source Handling** | Non-blocking language detection, mixed Arabic/English input support, canonical language enforcement, and localized cultural adaptation | **Implemented & Offline-Tested** |
| **Persistent Presenter & Storyboard Planner** | Automated layout routing (`presenter_left_visual_right`, `presenter_right_visual_left`, `presenter_picture_in_picture`, `presenter_center_with_overlays`, `media_full`, `quiz_card`) | **Implemented & Offline-Tested** *(Phase 10 persistent presenter validated locally)* |
| **Scene-Based Visual Demonstrations & Animation Engine** | Generic cross-domain `StoryboardPlanner.build_demonstration_plan()` (`AnimationStep` + `SceneMediaPlan`), narration-synchronized `process_demonstration` procedural vector renderer (`motion_animator.py`), HarfBuzz/raqm Arabic RTL canvas text, and provider-independent extension point | **Implemented & Offline-Tested** *(procedural 2D vector demonstrations verified offline; photorealistic physical action video requires an AI video provider or uploaded footage)* |
| **Non-Blocking Background Rendering** | `POST /api/v1/projects/{id}/render` returns `HTTP 202 Accepted` immediately, executes `orchestrator.run_project()` on a dedicated worker thread outside Uvicorn's asyncio event loop, enforces `409 Conflict` duplicate-render protection, and supports 2.5s Studio polling with browser-refresh resumption | **Implemented & Offline-Tested** *(in-process thread lifecycle; process-restart job recovery is not implemented)* |
| **Neural TTS (Edge-TTS)** | Multilingual neural voice synthesis (`ar-SA-HamedNeural`, `en-US-ChristopherNeural`, `bn-BD-BashkarNeural`, etc.) with timing metadata | **Implemented & Locally Verified** |
| **Local Talking Avatar (SadTalker CUDA)** | Subprocess-isolated SadTalker runtime generating lip-synced presenter video on local NVIDIA GPU (talking-head lip-sync & head motion only; not full-body demonstration) | **Implemented & Locally Verified** *(requires local CUDA GPU & SadTalker weights)* |
| **Arabic RTL Subtitles (`.ass` / `.srt` / `.vtt`)** | HarfBuzz/libass-compatible SubStation Alpha subtitles with proper RTL alignment and shaping | **Implemented & Locally Verified** |
| **FFmpeg 1080p Video Composition** | Multi-track 1920×1080 H.264/AAC assembly preserving animated `motion_video_path` streams, presenter overlays (split-screen / PiP / center studio), and burned subtitles | **Implemented & Locally Verified** |
| **Next.js Video Studio v2 Frontend** | Dashboard, 5-step Create Wizard, 3-column Scene Studio with async render polling & refresh resumption, Timeline Strip, Media Library, Export View, and Engine Diagnostics | **Implemented & Verified** (`33/33` unit tests, `tsc --noEmit` 0 errors) |
| **Cloud Avatars (HeyGen) & Generative B-Roll (Google Veo)** | Gated integrations behind `ENABLE_LIVE_HEYGEN` / paid-credit acknowledgement and procedural motion fallback | **Experimental / Gated Off by Default** *(no live paid calls enabled)* |
| **Distributed Multi-Node Locking & Persistent Render Queue** | PostgreSQL/Redis-backed project state and process-restart-safe render job queue | **Planned** |

---

## 5. Product Screenshots

All screenshots below are captured directly from the Next.js Video Studio v2 application (`docs/screenshots/v2/`).

### Dashboard & Project Catalog
![Dashboard](docs/screenshots/v2/01_dashboard.png)
*Main Studio Dashboard displaying recent projects, status indicators, quick actions, and engine readiness.*

![Projects Catalog](docs/screenshots/v2/09_projects_catalog.png)
*Projects Catalog view for browsing, filtering, and managing training video manifests.*

### Create Training Video Wizard
![Create Wizard — Content](docs/screenshots/v2/02_create_wizard.png)
*Step 1: Topic, source material, target audience, and strict duration budget.*

![Create Wizard — Languages](docs/screenshots/v2/03_languages_step.png)
*Step 2: Canonical language and multilingual target locale selection with RTL indicators.*

![Create Wizard — Video Style](docs/screenshots/v2/04_video_style.png)
*Step 3: Video style selection (`hybrid_presenter_broll`, `presenter_led`, `visual_explainer`, `demonstration_tutorial`, `corporate_training`).*

![Create Wizard — Presenter Configuration](docs/screenshots/v2/05_presenter_studio.png)
*Step 4: Presenter engine selection (`SadTalker Local`, `Mock`, optional gated `HeyGen`) and avatar portrait configuration.*

### AI Scene Studio & Interactive Timeline
![AI Scene Studio](docs/screenshots/v2/06_scene_editor.png)
*3-column Scene Studio with Scene List, 16:9 Preview Canvas, and Scene Inspector for narration, layout, and media editing.*

![Interactive Timeline](docs/screenshots/v2/07_timeline.png)
*Proportional multi-scene timeline strip showing scene sequence, durations, and active playhead.*

### Export & System Diagnostics
![Final Export](docs/screenshots/v2/08_final_export.png)
*Export view for previewing and downloading rendered multilingual 1080p MP4 videos.*

![Settings & Diagnostics](docs/screenshots/v2/10_settings_diagnostics.png)
*Engine diagnostics panel reporting backend health, LLM provider configuration, TTS, GPU/SadTalker, and FFmpeg availability.*

---

## 6. Complete System Architecture

```mermaid
flowchart TB
    subgraph Frontend["Next.js 14 Studio Frontend (web/)"]
        UI_Dash["Dashboard & Projects Catalog"]
        UI_Wiz["5-Step Create Wizard"]
        UI_Studio["AI Scene Studio & Timeline"]
        UI_Export["Export & Diagnostics"]
        API_Client["Typed API Client (web/src/lib/api.ts)"]
        UI_Dash --> API_Client
        UI_Wiz --> API_Client
        UI_Studio --> API_Client
        UI_Export --> API_Client
    end

    subgraph Backend["FastAPI Backend (app/)"]
        Router["REST API Layer (app/api/v1/projects.py, health.py)"]
        Orch["ProjectOrchestrator (app/workflows/orchestrator.py)"]
        Manifest["ProjectManifestManager (app/workflows/manifest.py)"]
        Lock["OS File Locks & RequestLedger (storage.py)"]
        Checkpoint["ScriptCheckpoint v2 (checkpoint.py)"]
        Graph["LangGraph Script Workflow (graph.py, nodes.py, staged_generator.py)"]
        Planner["StoryboardPlanner"]
        Loc["LocalizationService"]
        Dur["DurationReconciliationService"]

        API_Client <-->|HTTP JSON / Static Storage| Router
        Router --> Orch
        Router --> Manifest
        Orch --> Lock
        Orch --> Checkpoint
        Orch --> Manifest
        Orch --> Graph
        Orch --> Planner
        Orch --> Loc
        Orch --> Dur
    end

    subgraph Providers["Provider Abstractions (app/services/)"]
        LLM["LLM Providers: OpenRouterProvider (default free) / GroqProvider (gated)"]
        TTS["TTS Providers: EdgeTTSProvider (default) / Azure / Mock"]
        Avatar["Avatar Providers: SadTalker (Local CUDA) / Mock / HeyGen (gated)"]
        Visual["Visual & B-Roll: LocalMotionVisualProvider / Veo (gated)"]
        Sub["Subtitle Engine: ASS (Arabic RTL HarfBuzz) / SRT / VTT"]
        Comp["FFmpegCompositionProvider (1080p H.264/AAC)"]
    end

    subgraph Storage["Local Project Storage (storage/projects/{project_id}/)"]
        PJson["project.json"]
        Ledger["script_requests.json"]
        CPFiles["script_checkpoints/{identity_hash}.json"]
        Assets["scripts/ audio/ avatars/ visuals/ subtitles/ final/"]
    end

    Graph --> LLM
    Loc --> LLM
    Orch --> TTS
    Orch --> Avatar
    Orch --> Visual
    Orch --> Sub
    Orch --> Comp

    Manifest <--> PJson
    Lock <--> Ledger
    Checkpoint <--> CPFiles
    Comp --> Assets
```

---

## 7. End-to-End Video Generation Workflow

```mermaid
flowchart LR
    A["1. User Input\n(Topic / Source / Locale / Duration)"] --> B["2. Project Creation\n(project.json)"]
    B --> C["3. Normalize Input\n(Non-blocking Language Detection)"]
    C --> D["4. ContentAnalysis\n(Learning Objectives & Structure)"]
    D --> E["5. Stage 1: ScriptOutline\n(Title, Hooks, Scene Plan)"]
    E --> F["6. Stage 2: Sequential SceneDrafts\n(Scene 1..N with Context)"]
    F --> G["7. Stage 3-5: Assembly, Validation\n& Targeted Scene Repair"]
    G --> H["8. FinalScript & StoryboardPlanner\n(scripts/source.json)"]
    H --> I["9. Localization\n(Target Locales & RTL Metadata)"]
    I --> J["10. Neural TTS\n(Edge-TTS Audio per Scene)"]
    J --> K["11. Duration Reconciliation\n(Speech-Rate Calibration)"]
    K --> L["12. Avatar & Scene Media\n(SadTalker CUDA + Motion B-Roll)"]
    L --> M["13. Subtitle Generation\n(ASS / SRT / VTT with Arabic RTL)"]
    M --> N["14. FFmpeg 1080p Composition\n(H.264 / 48kHz Stereo AAC)"]
    N --> O["15. Final Export\n(final/training_{locale}.mp4)"]
```

---

## 8. Backend Architecture

The Python backend (`app/`) follows a layered, provider-abstracted architecture:

- **API Layer (`app/api/v1/`)**:
  - `projects.py`: Project CRUD, summary listing, canonical script generation (`POST /api/v1/projects/{id}/generate-script`), Studio bootstrap (`prepare`), scene editing/reordering, media uploads, full pipeline execution, and render status. Returns `409 Conflict` when another process/thread holds `.script.lock`.
  - `health.py`: Live readiness diagnostics for backend, storage, LLM provider configuration, TTS, FFmpeg, and GPU/SadTalker.
- **Orchestration & Persistence (`app/workflows/`)**:
  - `orchestrator.py`: Coordinates all stages, acquires OS-backed `.script.lock`, manages `RunControl`, verifies completed-script identity before fast-path reuse, and persists `scripts/source.json` atomically.
  - `manifest.py`: OS-locked (` .manifest.lock`), `fsync`ed atomic `project.json` persistence that projects authoritative request counts from `script_requests.json` and safely reads v2 checkpoints without losing metadata on corrupt files.
  - `storyboard_planner.py`: Assigns persistent presenter layouts, media types, and provider routing per scene.
- **Schemas & Configuration (`app/models/schemas.py`, `app/core/config.py`)**:
  - Pydantic v2 data contracts (`TrainingVideoRequest`, `ContentAnalysis`, `ScriptOutline`, `SceneDraft`, `ScriptDraft`, `FinalScript`, `LocalizedScript`, `ProjectManifest`) and environment-driven `Settings`.

---

## 9. Frontend Architecture

The frontend (`web/`) is built with **Next.js 14.2 (App Router)**, **React 18**, **TypeScript**, and **Tailwind CSS**:

- `web/src/app/page.tsx`: Dashboard with recent projects, status badges, and quick actions.
- `web/src/app/create/page.tsx`: 5-step guided creation wizard with source/canonical/target language controls and double-submission protection.
- `web/src/app/studio/[id]/page.tsx`: 3-column interactive Scene Studio with pre-render placeholder safety (eliminating 404 video spam), scene inspector, and proportional timeline strip.
- `web/src/app/studio/[id]/export/page.tsx`: Final video playback and download interface.
- `web/src/app/projects/page.tsx`, `web/src/app/media/page.tsx`, `web/src/app/settings/page.tsx`: Catalog, media library, and engine diagnostics.
- `web/src/lib/api.ts`: Centralized API client with structured FastAPI error parsing (`400`, `409`, `422`, `504` / proxy timeout handling).

---

## 10. AI & LLM Integration

LLM access is strictly abstracted behind `LLMProvider` (`app/services/llm/base.py`) and resolved via `app/services/llm/factory.py`:

- **OpenRouterProvider (`app/services/llm/openrouter_provider.py`)**:
  - Default configured model: `openrouter/free` via `https://openrouter.ai/api/v1`.
  - Uses concrete JSON instance templates (`build_json_instance_template()` in `app/services/llm/schema_utils.py`) rather than raw `$defs` JSON Schema dumps in prompt/repair modes, eliminating schema-echo responses on small/free models.
  - Strictly requires valid JSON in `message.content` — `message.reasoning` is never accepted as final structured output.
  - Classifies empty/reasoning-only responses (`OpenRouterReasoningOnlyError`), reasoning token exhaustion (`OpenRouterTokenBudgetExhaustedError`), decompression errors (`OpenRouterDecodingError`), timeouts (`OpenRouterTimeoutError`), cancellations (`OpenRouterCancelledError`), and unauthorized paid models (`OpenRouterPaidModelBlockedError`).
- **GroqProvider (`app/services/llm/groq_provider.py`)**:
  - Preserved for backward compatibility and unit testing; blocked during canonical script generation unless `ALLOW_PAID_SCRIPT_PROVIDERS=True`.

---

## 11. Script Generation Pipeline

Implemented in `app/workflows/script_generation/` (`graph.py`, `nodes.py`, `staged_generator.py`, `prompts.py`, `validators.py`):

1. **Normalize Input**: Validates duration bounds (`15–3600s`), normalizes locales, and records non-blocking language mismatch advisories.
2. **Content Analysis (`ContentAnalysis`)**: Extracts topic summary, key concepts, learning objectives (`LO1..LOk`), recommended scene count, and factual constraints in the canonical output language (with bounded 1-call language correction if needed).
3. **Stage 1 — Script Outline (`ScriptOutline`)**: Produces a compact outline (~250–400 tokens) with title, opening hook, closing summary, and `scene_outlines`. Deterministically assigns 100% of learning objectives and distributes target durations across scenes.
4. **Stage 2 — Sequential Scene Generation (`SceneDraft`)**: Generates each scene independently (`scene_1..scene_N`), passing preceding scene narration for continuity and locale-calibrated WPM word budgets (`115 WPM` Arabic, `140 WPM` English, `120 WPM` Bengali).
5. **Stage 3 — Assembly**: Combines outline + scenes into `ScriptDraft`, populates V2 `SceneMediaPlan` fields via `SceneDraft.sync_scene_fields`, and normalizes spoken durations deterministically.
6. **Stage 4 & 5 — Validation & Targeted Scene Repair**: Runs `validate_script_draft()` (duration tolerance, objective coverage, opening hook/scene type, narration/visual integrity, canonical language). If defects occur, `repair_targeted_scenes()` persists `repair_tasks` to the checkpoint and regenerates **only the affected 1–2 scenes**.

---

## 12. Checkpoint & Resume Architecture

```mermaid
flowchart TD
    Start["POST /projects/{id}/generate-script"] --> Lock["Acquire OS Exclusive Lock\n(.script.lock)"]
    Lock -->|Locked by another worker| Busy["HTTP 409 Conflict\n(ScriptBusyError)"]
    Lock -->|Acquired| Auth["Fail-Closed Auth Check\n(Free-Only Policy)"]
    Auth --> Identity["Compute Complete Identity Hash\n(Request + Model + Endpoint + Sources +\nPrompts + Schemas + Settings + WPM)"]
    Identity --> FastPath{"Completed Script &\nIdentity Matches?"}
    FastPath -->|Yes & not forced| ReturnCached["Return Verified Cached FinalScript"]
    FastPath -->|No| OpenLedger["Open Checksummed RequestLedger\n(script_requests.json)"]
    OpenLedger --> OpenCP["Open/Validate ScriptCheckpoint v2\n(Checksum + Envelope + Lineage)"]
    OpenCP -->|Missing Referenced or Corrupt| FailExplicit["Fail Explicitly\n(Preserve Corrupt File & Accounting)"]
    OpenCP -->|Valid| RunStages["Execute Staged Pipeline\n(Reuse Accepted analysis, outline, scene_1..k)"]
    RunStages --> Reserve["Pre-Transport Reservation\n(Unique 32-hex ID in RequestLedger)"]
    Reserve --> CallLLM["OpenRouter Streaming Call\n(Wall-Clock Watchdog + RunControl)"]
    CallLLM --> Outcome["Record Outcome in Ledger\n(completed / failed)"]
    Outcome --> ValidateStage{"Stage Valid?"}
    ValidateStage -->|Yes| CommitCP["Atomic Checksummed Commit\n(fsync + os.replace + Dependency Hash)"]
    ValidateStage -->|Timeout / Error| FinishFail["checkpoint.finish(False, reason)\nPreserve Accepted Stages for Resume"]
    CommitCP --> NextStage{"More Stages?"}
    NextStage -->|Yes| RunStages
    NextStage -->|No| Finalize["Atomic scripts/source.json +\nproject.json (script_identity_hash)"]
```

**Key Properties**:
- **Complete Identity Invalidation**: Changing the source text, model, endpoint, prompts, schemas, reasoning/token settings, or WPM timing assumptions generates a new `identity_hash` and invalidates stale completed scripts and checkpoints without deleting older files.
- **Lineage & Repair Persistence**: Replacing `scene_k` automatically archives dependent downstream scenes (`order > k`) with `reason="predecessor_changed"` and resets them to `pending`. Pending `repair_tasks` and `revision_count` survive restarts.
- **Single-Machine Scope**: Locking uses `msvcrt.locking` on Windows and `fcntl.flock` on POSIX.

---

## 13. Error Handling & Retry Architecture

```mermaid
flowchart TD
    Req["OpenRouterProvider._read_chat_completion()"] --> Gate["assert_model_authorized()"]
    Gate -->|Paid / Unverified| E_Paid["OpenRouterPaidModelBlockedError\n(0 retries, 0 budget consumed)"]
    Gate -->|Authorized| Reserve["RequestLedger.reserve()"]
    Reserve -->|Ceiling Reached| E_Cap["ValueError: Cumulative Limit Reached\n(0 transport calls)"]
    Reserve -->|Reserved| Stream["HTTPX client.stream('POST') +\nWall-Clock Watchdog Thread"]

    Stream -->|iter_bytes() decodes once;\nstrip Content-Encoding on Response| OK["HTTP 200 JSON"]
    Stream -->|httpx.DecodingError| E_Dec["OpenRouterDecodingError\n(Bounded: max 2 total attempts)"]
    Stream -->|Timeout / Blocked Stream| E_Conn["OpenRouterConnectionError\n(Bounded backoff within RunControl deadline)"]
    Stream -->|Explicit RunControl.cancel()| E_Can["OpenRouterCancelledError\n(Non-retryable -> SCRIPT_CANCELLED)"]
    Stream -->|260s RunControl Deadline| E_TO["OpenRouterTimeoutError\n(Non-retryable -> SCRIPT_TIMEOUT)"]

    OK -->|HTTP 401 / 402| E_Auth["Auth / Credits Error\n(Non-retryable)"]
    OK -->|HTTP 413| E_413["PayloadTooLarge\n(At most 1 compacted retry)"]
    OK -->|HTTP 429| E_429["RateLimitError\n(Retry-After aware backoff)"]
    OK -->|Empty content / Reasoning-only| E_Compat["OpenRouterModelCompatibilityError\n(Non-retryable, no JSON repair)"]
    OK -->|Malformed JSON in content| Repair["Single Bounded JSON Repair\n(Concrete instance template)"]
```

---

## 14. Multilingual & Localization Support

- **Non-blocking source language detection (`app/core/language.py`)**: Detects source script/language without blocking mismatched source-to-target workflows (e.g., English recipe → Arabic video, mixed Arabic/English → Arabic video).
- **Canonical & Target Localization (`app/services/localization/`)**: Supports cultural adaptation, terminology preservation, RTL metadata (`text_direction: "rtl"`), and per-locale asset directories.
- **Supported Locales**: `en-US`, `ar-SA`, `ar-EG`, `ar-AE`, `bn-BD`, `ur-PK`, `fr-FR`, `de-DE`, `es-ES` (with locale-calibrated speech rates in `LocaleDurationEstimator`).

---

## 15. Text-to-Speech Architecture

- **Default Provider**: `EdgeTTSProvider` (`app/services/tts/edge_tts_provider.py`) — free neural voices with per-locale voice mapping (e.g., `ar-SA-HamedNeural`, `en-US-ChristopherNeural`, `bn-BD-BashkarNeural`) and word-boundary metadata.
- **Optional Providers**: `AzureTTSProvider` (requires `AZURE_SPEECH_KEY`), `MockTTSProvider` (offline testing).
- **Duration Reconciliation (`app/services/duration/`)**: Measures actual synthesized speech duration per scene and reconciles narration pacing before avatar/video rendering.

---

## 16. Avatar Generation

- **Local Talking Avatar (`app/services/avatar/sadtalker_provider.py`)**: Subprocess-isolated SadTalker runtime executing on local NVIDIA CUDA GPUs (`.sadtalker-venv`) to produce lip-synced presenter clips at `$0.00` external API cost.
- **Mock Provider (`mock_provider.py`)**: Instant deterministic placeholder clips for offline UI/API testing.
- **HeyGen Cloud (`heygen_provider.py`)**: Optional integration gated behind `ENABLE_LIVE_HEYGEN=True` and explicit `ack_paid_credits=True`.

---

## 17. Scene-Based Visual Demonstrations, Animation Architecture & Narration Synchronization

- **Generic Scene Demonstration Planning (`app/workflows/storyboard_planner.py`, `app/models/schemas.py`)**:
  - `StoryboardPlanner.build_demonstration_plan()` dynamically analyzes any scene's title, purpose, narration, and visual direction (in English, Arabic, or other supported languages — with zero hardcoded topic recipes) to populate `SceneMediaPlan` with:
    - `demonstration_action`, `required_objects`, `object_movement`, `transition_to_next`, `is_animated_demonstration`, and `animation_provider_hint`.
    - `animation_sequence: List[AnimationStep]` — an ordered list of visual beats with word-proportional normalized timestamps (`start_ratio`, `end_ratio` spanning `0.0 -> 1.0`) and synchronized `narration_segment` clauses.
- **Narration & Animation Synchronization**:
  - Normalized step ratios (`start_ratio`..`end_ratio`) stretch automatically to the **exact measured TTS waveform duration** (`audio_asset.duration_seconds`) during `CompositionService.compose_locale_scenes()`, ensuring visual actions never finish prematurely or stall during long narration segments.
- **Procedural 2D Process Demonstration Renderer (`app/services/media/motion_animator.py`, `motion_visual_provider.py`)**:
  - Routes non-cybersecurity instructional scenes to the generic `process_demonstration` archetype (preventing cybersecurity cards from hijacking cooking, science, electronics, medical, or programming tutorials).
  - Renders continuous 25 FPS 1920×1080 video via Pillow + FFmpeg with native HarfBuzz/raqm Arabic RTL text shaping (`direction="rtl"`), a live procedural vector stage (`chop_rhythm`, `heat_pulse`, `stir_circular`, `pour_stream`, `layer_stack`, `orbit_flow`, `highlight_scan`, `showcase_reveal`), active object badges, and a synchronized right-hand step timeline (`DONE` / `ACTIVE` / `NEXT`).
  - Uses content-hashed caching (`v4_demo_motion`) so editing narration or visual direction invalidates stale motion clips.
- **Provider-Independent Extension Point (`app/services/media/base.py`, `service.py`, `factory.py`)**:
  - External generative AI video providers (Google Veo, or future Runway / Kling / local Wan2.1 / LTX-Video diffusers) plug in via `SceneMediaProvider` using `SceneMediaPlan` without modifying the orchestrator or silently enabling paid APIs.
- **Media Library**: Users can upload custom images/videos per project and bind them to individual scenes in the Studio Inspector.

---

## 17.1 Visual Demonstration Quality and Current Limitations

To be completely transparent about visual realism today:

- **What currently works well**:
  - **Talking-head presenter**: Local SadTalker (CUDA) produces real audio-driven lip-sync and natural head movement from a portrait image (`$0` API cost).
  - **Dynamic narration-synchronized procedural demonstrations**: Every demonstration scene receives a structured, multi-step visual plan (`AnimationStep` timeline) rendered as continuous 25 FPS procedural 2D vector motion synchronized to the measured TTS narration duration, with proper Arabic RTL rendering and preserved split-screen / PiP / full-media layouts in FFmpeg.
  - **Custom footage**: User-uploaded demonstration clips or photos are cleanly integrated into any scene.
- **What still needs improvement (honest limitations)**:
  - **Procedural vector graphics vs. photorealistic physical footage**: Zero-cost local rendering (`LocalMotionVisualProvider` + Pillow) generates stylized 2D procedural vector animations (heat waves, stirring orbits, pouring streams, stacked layers, circuit flows, step timelines) — **not** photorealistic video of human hands chopping onions, whisking real béchamel sauce, or lifting a baked pasta slice.
  - **SadTalker scope**: SadTalker animates a portrait head/face for lip-sync; it does **not** perform full-body physical demonstrations.
  - **Next step for photorealistic physical actions**: Integrating an enabled generative text-to-video / image-to-video backend (such as Vertex AI Veo when user-approved, or a local GPU video diffusion model like Wan2.1 / LTX-Video via the `SceneMediaProvider` interface) or uploading real recorded clips per scene.

---

## 18. Subtitle Generation & Arabic RTL Handling

- **Engine (`app/services/subtitles/`)**: Generates `.ass` (SubStation Alpha), `.srt`, and `.vtt` tracks synchronized to scene audio durations.
- **Arabic RTL**: Applies RTL text direction, proper font styling, and HarfBuzz/libass complex script shaping during FFmpeg burn-in so Arabic glyphs connect and align cleanly.

---

## 19. FFmpeg Video Composition & Non-Blocking Background Rendering

- **Native Compositor (`app/services/composition/ffmpeg_provider.py`)**:
  - Builds FFmpeg filtergraphs for persistent presenter layouts (`presenter_left_visual_right`, `presenter_right_visual_left`, `presenter_picture_in_picture`, `presenter_center_with_overlays`, `media_full`, `quiz_card`) while preserving continuous animation from `motion_video_path`.
  - Normalizes all scene audio streams to **48 kHz stereo AAC** and video streams to **1920×1080 H.264** prior to concatenation, and validates output clips via `ffprobe`.
- **Non-Blocking Background Rendering Architecture (`app/api/v1/projects.py`, `web/src/app/studio/[id]/page.tsx`)**:
  - Long renders (e.g., multi-scene SadTalker CUDA + FFmpeg composition taking 6+ minutes) previously exceeded Next.js's 300s proxy timeout and blocked Uvicorn's asyncio event loop.
  - `POST /api/v1/projects/{project_id}/render` now persists `status = "rendering"`, spawns a dedicated background worker thread outside the asyncio event loop, and returns **`HTTP 202 Accepted` immediately**.
  - Duplicate concurrent render requests for the same project are rejected with **`HTTP 409 Conflict`**.
  - The Studio UI polls `GET /api/v1/projects/{project_id}` every **2.5 seconds** for live stage progress (`localization_status`, `audio_status`, `avatar_status`, `visual_status`, `subtitle_status`, `composition_status`), resumes monitoring automatically after browser refresh, surfaces real backend failure errors, and displays completed videos directly without re-rendering.

```mermaid
sequenceDiagram
    participant UI as Studio UI (Next.js)
    participant API as FastAPI (Uvicorn Event Loop)
    participant Worker as Background Render Thread
    participant Disk as project.json & Media Assets

    UI->>API: POST /api/v1/projects/{id}/render
    API->>Disk: Save status="rendering"
    API->>Worker: Start daemon thread (orchestrator.run_project)
    API-->>UI: HTTP 202 Accepted (<1s)
    Note over UI,API: Event loop stays responsive; duplicate POST returns 409 Conflict
    loop Every 2.5s (survives browser refresh)
        UI->>API: GET /api/v1/projects/{id}
        API->>Disk: Read live stage statuses
        API-->>UI: status="rendering", audio/avatar/visual/composition_status
    end
    Worker->>Disk: Write final/training_{locale}.mp4 & status="completed" (or "failed")
    UI->>API: GET /api/v1/projects/{id}
    API-->>UI: status="completed"
    UI->>UI: Load scenes & display final video preview
```

---

## 20. Final Video Export

- Assembled videos are persisted to `storage/projects/{project_id}/final/training_{locale}.mp4` and served via FastAPI static routes for in-browser playback, scrubbing, and download on the Studio Export page (`/studio/[id]/export`).

---

## 21. Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend** | Python 3.10–3.13, FastAPI, Uvicorn, Pydantic v2, LangGraph, HTTPX (`0.28.1`), HTTPCore (`1.0.9`) |
| **Frontend** | Next.js 14.2 (App Router), React 18, TypeScript 5, Tailwind CSS 3.4, Lucide Icons |
| **AI & Media** | OpenRouter API (`openrouter/free`), Groq SDK (optional), Edge-TTS, SadTalker (Local CUDA), Pillow, FFmpeg / FFprobe |
| **Testing** | Pytest (backend), Node.js native test runner (`node --test`, frontend), ESLint, TypeScript compiler |

---

## 22. Repository Structure

```text
AI-Multilingual-Training-Video-Generator/
├── app/
│   ├── api/v1/                 # FastAPI routers (projects.py, health.py)
│   ├── core/                   # Configuration (config.py), logging, language detection
│   ├── models/                 # Pydantic v2 schemas (schemas.py)
│   ├── services/
│   │   ├── llm/                # OpenRouterProvider, GroqProvider, schema_utils, factory
│   │   ├── localization/       # Multilingual adaptation & locale utilities
│   │   ├── tts/                # Edge-TTS, Azure TTS, Mock TTS
│   │   ├── avatar/             # SadTalker (CUDA), Mock, HeyGen (gated)
│   │   ├── visuals/            # LocalMotionVisualProvider, Veo (gated)
│   │   ├── subtitles/          # ASS/SRT/VTT generation & RTL formatting
│   │   ├── composition/        # FFmpeg 1080p compositor & ffprobe validation
│   │   └── duration/           # Audio duration reconciliation
│   └── workflows/
│       ├── orchestrator.py     # End-to-end project orchestrator + OS locking + RunControl
│       ├── manifest.py         # Atomic OS-locked project.json persistence
│       ├── storyboard_planner.py
│       └── script_generation/  # LangGraph workflow, staged_generator, checkpoint, storage
├── web/                        # Next.js 14 Studio v2 frontend
├── docs/                       # Technical audits, checkpoint design docs, screenshots
├── scripts/                    # Local studio helpers & verification utilities
├── tests/                      # Backend Pytest suites
├── .env.example                # Safe environment variable template
└── README.md
```

---

## 23. Technical Documentation

| Document | Category | Description |
| :--- | :--- | :--- |
| [Checkpoint & Resume Reliability Audit](docs/CHECKPOINT_RESUME_RELIABILITY_AUDIT.md) | Reliability / Audit | Detailed audit of cross-process locking, request accounting, generation identity, paid-model gates, and deadline enforcement |
| [Script Checkpoint & Resume Design](docs/SCRIPT_CHECKPOINT_RESUME.md) | Architecture | Checkpoint schema, resumption lifecycle, and progress projection |
| [OpenRouter Script Audit](docs/OPENROUTER_SCRIPT_AUDIT.md) | Provider Integration | OpenRouter structured-output, reasoning token, and free-router behavior analysis |
| [Project Technical Audit](docs/PROJECT_TECHNICAL_AUDIT.md) | Technical Audit | End-to-end codebase and pipeline technical review |
| [Video Realism Gap & API Research](docs/research/VIDEO_REALISM_GAP_AND_API_RESEARCH_REPORT.md) | Research | Comparative evaluation of talking-avatar and generative B-roll engines |

---

## 24. Installation Prerequisites

- **Python**: 3.10 – 3.13
- **Node.js**: 18+ (for Next.js 14 frontend)
- **FFmpeg & FFprobe**: 6.0+ / 7.0+ available on `PATH` (compiled with `libx264`, `aac`, `libass` / HarfBuzz)
- **Optional (Local Avatar)**: NVIDIA GPU with CUDA drivers and isolated `.sadtalker-venv` for SadTalker

---

## 25. Environment Configuration

Copy `.env.example` to `.env` and set your keys locally (`.env` is gitignored and must never be committed):

```powershell
Copy-Item .env.example .env
```

Key script-generation and safety settings:

```ini
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_openrouter_api_key_here
OPENROUTER_MODEL=openrouter/free
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_TIMEOUT_SECONDS=90.0
OPENROUTER_SCRIPT_TIMEOUT_SECONDS=260
OPENROUTER_SCRIPT_PROJECT_REQUEST_LIMIT=48
OPENROUTER_REASONING_MIN_OUTPUT_TOKENS=8192

# Fail-closed cost protection (keep False unless paid spend is explicitly approved)
OPENROUTER_ALLOW_PAID_MODELS=False
OPENROUTER_VERIFIED_FREE_MODELS=openrouter/free
ALLOW_PAID_SCRIPT_PROVIDERS=False
ENABLE_LIVE_API_TESTS=False
```

---

## 26. Backend Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 27. Frontend Setup

```powershell
cd web
npm install
```

---

## 28. Running the Application

Run the backend and frontend in two separate terminals from the repository root:

**Terminal 1 — FastAPI Backend (`http://127.0.0.1:8000`)**
```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — Next.js Studio Frontend (`http://127.0.0.1:3000`)**
```powershell
cd web
npm run dev
```

Open `http://127.0.0.1:3000` in your browser. Interactive API docs are available at `http://127.0.0.1:8000/docs`.

---

## 29. Testing & Verification

All verification runs below were executed **offline** (no paid API calls, no live OpenRouter/Groq requests, no live video rendering):

### Backend — Targeted Background Rendering & Visual Demonstration Suite
```powershell
.\.venv\Scripts\python.exe -m pytest -v tests/test_background_rendering_and_animation.py tests/test_v2_render_and_preview.py
```
- **Observed Result**: **14 passed, 0 failed** (verifies HTTP 202 immediate return, responsive event loop, 409 duplicate-render guard, persisted failure reporting, browser-refresh polling resumption, generic multilingual demonstration planning, non-hijacked archetypes, and audio-synchronized composition).

### Backend — Full Repository Offline Suite
```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/ --ignore=tests/test_master_local_pipeline.py
```
- **Observed Result**: **452 passed, 0 failed**.

### Frontend
```powershell
cd web
npx tsc --noEmit
npm test
```
- **`npx tsc --noEmit`**: **Passed** (`0` TypeScript errors).
- **`npm test`**: **33 passed, 0 failed** (`293ms`).

---

## 30. Security & Cost Controls

- **Fail-Closed Paid-Model Gate**: `OpenRouterProvider.assert_model_authorized()` refuses paid models, unverified `:free` suffixes, and non-official endpoints before budget reservation and before transport unless `OPENROUTER_ALLOW_PAID_MODELS=True`.
- **No Silent Provider Switching**: `ProjectOrchestrator` refuses `GroqProvider` unless `ALLOW_PAID_SCRIPT_PROVIDERS=True`.
- **Cumulative Request Ceiling**: `RequestLedger` (`script_requests.json`) enforces a durable per-project reservation cap (`OPENROUTER_SCRIPT_PROJECT_REQUEST_LIMIT=48`) that survives crashes and stale manifest writes.
- **Secret Hygiene**: `.env` is excluded via `.gitignore`; `sanitize_diagnostic_message()` redacts `sk-or-...` and `gsk_...` tokens from manifest error records.

---

## 31. Current Limitations

- **Photorealistic Physical Action Video**: Zero-cost local visual demonstrations (`LocalMotionVisualProvider` + `motion_animator.py`) render stylized, narration-synchronized 2D procedural vector animations and step timelines — not photorealistic footage of physical hand/object manipulation. Photorealistic demonstrations require either an enabled generative AI video provider (e.g., Vertex AI Veo or a local GPU video diffusion model) or user-uploaded footage.
- **SadTalker Scope**: Local SadTalker generates lip-synced talking-head video from a portrait image; it does not perform full-body gestures or physical demonstrations.
- **In-Process Render Thread Scope**: `POST /api/v1/projects/{id}/render` runs in a background worker thread inside the FastAPI process. Browser refreshes seamlessly resume polling, but if the FastAPI server process itself restarts mid-render, the in-memory job does not automatically resume (users can re-trigger render, and cached completed stages are reused).
- **Free-Router Latency**: `openrouter/free` routes requests across shared third-party free endpoints; a 6-scene script may hit the 260-second run deadline and require 1–2 manual retries to resume remaining scenes from checkpoint.
- **Single-Machine Local Storage**: OS file locks (`msvcrt.locking` / `fcntl.flock`) protect concurrent local processes on one machine, not distributed multi-node deployments or network shares.

---

## 32. Development Roadmap & Future Improvements

- **Short-Term**: Add Studio UI controls for inspecting per-scene `AnimationStep` timelines and cancelling active background renders; integrate optional local GPU video diffusion (e.g., Wan2.1 / LTX-Video) via `SceneMediaProvider`.
- **Medium-Term**: Support optional user-approved paid/fast OpenRouter models and Vertex AI Veo with real-time cost telemetry; add FFmpeg crossfade scene transitions honoring `SceneMediaPlan.transition_to_next`.
- **Long-Term**: Migrate manifest, ledger, and background render job queue to SQLite/PostgreSQL + Redis/Celery for process-restart recovery and multi-worker cloud deployment.

---

## 33. Author

Developed by **Ali Developments** — [GitHub Repository](https://github.com/Ali-Developments/AI-Multilingual-Training-Video-Generator).
