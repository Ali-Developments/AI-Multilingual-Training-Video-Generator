# System Architecture

## 1. Architectural Philosophy
The **AI Multilingual Training Video Generation Platform** is engineered following Clean Architecture and Domain-Driven Design principles:
- **Vendor Abstraction**: All external infrastructure and third-party APIs (LLM, TTS, Avatar, Subtitles, Visuals, FFmpeg) reside behind explicit abstract base classes. Business logic depends solely on these interfaces.
- **Timing Synchronization Ground Truth**: Audio waveform measurement (`ffprobe` and `wave`) serves as the immutable ground-truth timing source for all downstream video segments, avatar lip-sync, visual displays, and subtitle cues.
- **Post-TTS Duration Reconciliation**: After real speech is synthesized, the dedicated `DurationReconciliationService` dynamically budgets, condenses, and re-synthesizes audio if measured durations overrun target video limits (e.g., target 30s).
- **Free Local Neural Avatar Generation**: The isolated `SadTalkerProvider` synthesizes audio-driven talking-head presenter videos on consumer NVIDIA GPUs without any external API calls or wallet costs.
- **Multi-Locale Fault Isolation**: Pipeline failures on a specific target locale never abort or invalidate sibling locales that succeeded.
- **Content-Aware Caching & Idempotency**: Sidecar `.meta.json` files track text, voice, image, audio, and parameter hashes. Modifying script narration automatically invalidates downstream TTS, avatars, subtitles, and composed videos without requiring manual cache flushing.

```text
               +-----------------------------+
               |   Streamlit Frontend Studio |
               +--------------+--------------+
                              | HTTP / REST or Direct Bridge
                              v
               +-----------------------------+
               |      FastAPI Backend        |
               +--------------+--------------+
                              |
               +--------------v--------------+
               |     Project Orchestrator    |
               +--------------+--------------+
                              |
        +---------------------+---------------------+
        |          |          |          |          |
 +------v---+ +----v----+ +---v----+ +---v----+ +---v----+
 |   LLM    | |   TTS   | | Avatar | |Visuals | |Subtitles|
 | Provider | | Provider| |Provider| |Provider| |Provider |
 +----------+ +---------+ +--------+ +--------+ +---------+
        |          |          |          |          |
        |          v          |          |          |
        |     Post-TTS Dur.   |          |          |
        |    Reconciliation   |          |          |
        +----------+----------+          |          |
                   |                     |          |
                   +---------------------+----------+
                              |
               +--------------v--------------+
               | Composition Provider (FFmpeg)|
               | (Normalized 48kHz Stereo AAC)|
               +--------------+--------------+
                              |
               +--------------v--------------+
               |  Atomic Manifest & Storage  |
               +-----------------------------+
```

---

## 2. Core Service Provider Matrix

| Interface | Default / Local Provider | Alternate / External Provider | Key Responsibilities |
| :--- | :--- | :--- | :--- |
| `LLMProvider` | `GroqProvider` (`openai/gpt-oss-20b`) | `MockLLMProvider` | Pedagogical analysis, scene drafting, cultural adaptation, and script condensation. |
| `TTSProvider` | `EdgeTTSProvider` (`ar-SA-HamedNeural`) | `MockTTSProvider`, `AzureTTSProvider` | Free native speech synthesis with accurate locale voices and exact waveform measurement. |
| `DurationService` | `DurationReconciliationService` | N/A | Post-TTS waveform verification, proportional scene budgeting, and multi-round condensation. |
| `AvatarProvider` | `SadTalkerProvider` (Local Free) | `MockAvatarProvider`, `HeyGenProvider` (Paid API) | Isolated audio-driven talking-head presenter synthesis on CUDA or cloud APIs. |
| `VisualAssetProvider`| `LocalVisualProvider` | `MockVisualProvider` | 1920x1080 slide graphics with Unicode font rendering (Arabic & Bengali). |
| `SubtitleProvider` | `DeterministicSubtitleProvider` | Extensible to Whisper | Substation Alpha (`.ass`) with complex RTL HarfBuzz shaping, `.srt`, and `.vtt`. |
| `CompositionProvider`| `FFmpegCompositionProvider` | `MockCompositionProvider` | Multi-track composition, PiP presenter paneling, audio normalization (48k stereo AAC), and concatenation. |

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
