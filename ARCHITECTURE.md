# System Architecture — AI Training Video Studio V2

## 1. Architectural Philosophy
The **AI Multilingual Training Video Generation Platform (Studio V2)** is engineered following Clean Architecture and Domain-Driven Design principles:
- **Presenter-Led Video Hierarchy**: Eliminates PowerPoint-style slide cards and tiny corner avatars in favor of balanced split-screen (`presenter_split`, 42% presenter / 58% media), framed presenter (`presenter_full`), and full-bleed cinematic B-roll (`media_full`).
- **Storyboard Planner**: Intelligently allocates presenter vs. B-roll vs. motion visual vs. quiz vs. outro scenes based on educational style (`hybrid_presenter_broll`, `demonstration_tutorial`, etc.).
- **Timing Synchronization Ground Truth**: Audio waveform measurement (`ffprobe` and `wave`) serves as the immutable ground-truth timing source for all downstream video segments, avatar lip-sync, visual displays, and subtitle cues.
- **Post-TTS Duration Reconciliation**: After real speech is synthesized, the dedicated `DurationReconciliationService` dynamically budgets, condenses, and re-synthesizes audio if measured durations overrun target video limits (e.g., target 30s).
- **Free Local Neural Avatar Generation**: The isolated `SadTalkerProvider` synthesizes audio-driven talking-head presenter videos on consumer NVIDIA GPUs without any external API calls or wallet costs.
- **Local Motion Visuals**: Transforms static scene graphics into cinematic motion B-roll via FFmpeg's `zoompan` Ken Burns filter.
- **Multi-Locale Fault Isolation**: Pipeline failures on a specific target locale never abort or invalidate sibling locales that succeeded.
- **Content-Aware Caching & Idempotency**: Modifying script narration automatically invalidates downstream TTS, avatars, subtitles, and composed videos without requiring manual cache flushing.

```text
               +-------------------------------------------+
               |   Next.js 14 App Router Studio (web/)     |
               | (Dashboard, Wizard, Scene Studio, Export) |
               +---------------------+---------------------+
                                     | HTTP / REST (Rewrites)
                                     v
               +-------------------------------------------+
               |              FastAPI Backend              |
               |       (/api/v1/projects, /storage)        |
               +---------------------+---------------------+
                                     |
                       +-------------v-------------+
                       |    Project Orchestrator   |
                       +-------------+-------------+
                                     |
               +---------------------+---------------------+
               |                     |                     |
        +------v-----+        +------v-----+        +------v-----+
        |  LLM / Groq|        | Storyboard |        |    TTS     |
        |  (Script)  |        |  Planner   |        | (Edge-TTS) |
        +------+-----+        +------+-----+        +------+-----+
               |                     |                     |
               v                     |                     v
        +------------+               |              +------------+
        |Localization|               |              |Post-TTS Dur|
        |  (ar-SA)   |               |              |Reconcile   |
        +------+-----+               |              +------+-----+
               |                     |                     |
               +---------------------+---------------------+
                                     | Approved Audio & Timing
               +---------------------+---------------------+
               |                     |                     |
        +------v-----+        +------v-----+        +------v-----+
        |  SadTalker |        |Local Motion|        | Subtitles  |
        | Local CUDA |        |Visual/Broll|        | (libass)   |
        +------+-----+        +------+-----+        +------+-----+
               |                     |                     |
               +---------------------+---------------------+
                                     |
                       +-------------v-------------+
                       |    FFmpeg Scene Composer  |
                       | (Presenter Split/Full HD) |
                       +-------------+-------------+
                                     |
                       +-------------v-------------+
                       | Final Multilingual Video  |
                       | (1920x1080 48kHz AAC MP4) |
                       +---------------------------+
```

---

## 2. Core Service Provider Matrix

| Interface | Default / Local Provider | Alternate / External Provider | Key Responsibilities |
| :--- | :--- | :--- | :--- |
| `LLMProvider` | `GroqProvider` (`openai/gpt-oss-20b`) | `MockLLMProvider` | Pedagogical analysis, scene drafting, cultural adaptation, and script condensation. |
| `TTSProvider` | `EdgeTTSProvider` (`ar-SA-HamedNeural`) | `MockTTSProvider`, `AzureTTSProvider` | Free native speech synthesis with accurate locale voices and exact waveform measurement. |
| `DurationService` | `DurationReconciliationService` | N/A | Post-TTS waveform verification, proportional scene budgeting, and multi-round condensation. |
| `AvatarProvider` | `SadTalkerProvider` (Local Free) | `MockAvatarProvider`, `HeyGenProvider` (Paid API) | Isolated audio-driven talking-head presenter synthesis on CUDA or cloud APIs. |
| `SceneMediaProvider` | `LocalMotionVisualProvider`, `UploadedMediaProvider` | `OptionalGeneratedVideoProvider` | Ken Burns slow zoom/pan motion clips, user media assets. |
| `VisualAssetProvider`| `LocalVisualProvider` | `MockVisualProvider` | 1920x1080 background graphics with Unicode font rendering (Arabic RTL & English LTR). |
| `SubtitleProvider` | `DeterministicSubtitleProvider` | Extensible to Whisper | SubStation Alpha (`.ass`) with complex RTL HarfBuzz shaping, `.srt`, and `.vtt`. |
| `CompositionProvider`| `FFmpegCompositionProvider` | `MockCompositionProvider` | Multi-track composition, `presenter_split`, `presenter_full`, audio normalization (48k stereo AAC), and concatenation. |

---

## 3. Storage & Artifact Hierarchy

Projects are encapsulated under `storage/projects/<project_id>/`:
```text
storage/projects/<project_id>/
├── project.json                      # Atomic authoritative pipeline state
├── project.json.lock                 # Concurrency write lock
├── acceptance_report.json            # Automated timeline audit & performance report
├── scripts/
│   ├── canonical.json                # Master pedagogical English script
│   └── <locale>.json                 # Culturally adapted localized script (e.g. ar-SA.json)
├── audio/
│   └── <locale>/
│       ├── scene_<id>.mp3            # Measured scene speech waveforms
│       └── scene_<id>.mp3.meta.json  # Audio provenance & narration hash
├── avatars/
│   └── <locale>/
│       ├── scene_<id>.mp4            # Presenter talking-head video
│       ├── scene_<id>.job.json       # Inference timing and job metadata
│       └── scene_<id>.mp4.meta.json  # Input audio & portrait provenance
├── visuals/
│   └── <locale>/
│       └── scene_<id>.png            # Full HD 1920x1080 supporting slide card
├── subtitles/
│   └── <locale>/
│       ├── scene_<id>.srt            # SubRip Subtitle file
│       ├── scene_<id>.vtt            # WebVTT cue file
│       └── scene_<id>.ass            # Advanced SubStation Alpha with RTL styling
├── rendered/
│   └── <locale>/
│       └── scene_<id>.mp4            # Pre-composed scene video (48kHz stereo AAC)
└── final/
    └── training_<locale>.mp4         # Master composed multilingual training video
```

---

## 4. SadTalker Runtime Isolation
- **Application Environment (`.venv`):** Python 3.13+ containing backend services and orchestrator.
- **SadTalker Environment (`.sadtalker-venv`):** Python 3.10 with CUDA 11.8 PyTorch.
- **Invocation:** Subprocess adapter with non-shell execution (`app/services/avatar/sadtalker_provider.py`), deterministic canonical output resolution, and strict timeout protection.
