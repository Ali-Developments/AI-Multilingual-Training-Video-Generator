# System Architecture

## 1. Architectural Philosophy
The **AI Training Video Generation Platform** is engineered following Clean Architecture and Domain-Driven Design principles:
- **Vendor Abstraction**: All external infrastructure and third-party APIs (LLM, TTS, Avatar, Subtitles, Visuals, FFmpeg) reside behind explicit abstract base classes. Business logic depends solely on these interfaces.
- **Timing Synchronization Ground Truth**: Audio waveform measurement (`ffprobe` and `wave`) serves as the immutable ground-truth timing source for all downstream video segments, avatar lip-sync, visual displays, and subtitle cues.
- **Multi-Locale Fault Isolation**: Pipeline failures on a specific target locale never abort or invalidate sibling locales that succeeded.
- **Idempotency & Partial Resume**: Every generated artifact is recorded in an atomic `project.json` manifest. Re-running a completed or interrupted project reuses valid existing assets on disk.

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
        +---------------------+---------------------+
                              |
               +--------------v--------------+
               | Composition Provider (FFmpeg)|
               +--------------+--------------+
                              |
               +--------------v--------------+
               |  Atomic Manifest & Storage  |
               +-----------------------------+
```

---

## 2. Core Service Provider Matrix

| Interface | Default Provider | Alternate / Fallback | Key Responsibilities |
| :--- | :--- | :--- | :--- |
| `LLMProvider` | `GroqProvider` | `MockLLMProvider` | Text generation, script drafting, cultural localization via configuration-driven model ID. |
| `TTSProvider` | `EdgeTTSProvider` | `MockTTSProvider`, `AzureTTSProvider` | Speech synthesis with multi-locale voice mapping and duration measurement. |
| `AvatarProvider` | `MockAvatarProvider` | `HeyGenProvider` | Talking-head video segments for presenter scenes (`requires_avatar` logic). |
| `VisualAssetProvider` | `LocalVisualProvider` | `MockVisualProvider` | 1920x1080 slide graphics with Unicode font rendering (Arabic & Bengali). |
| `SubtitleProvider` | `DeterministicSubtitleProvider` | Future `WhisperProvider` | Monotonic proportional cue generation and `.srt`/`.vtt` serialization. |
| `CompositionProvider`| `FFmpegCompositionProvider` | `MockCompositionProvider` | Per-scene video composition and lossless concatenation into final MP4. |

---

## 3. Storage & Artifact Hierarchy

Projects are encapsulated under `storage/projects/<project_id>/`:
```text
storage/projects/<project_id>/
├── project.json                 # Atomic ProjectManifest tracking lifecycle and file paths
├── scripts/
│   ├── source.json              # Canonical English/Base FinalScript
│   ├── ar-SA.json               # Localized Arabic script (RTL)
│   └── bn-BD.json               # Localized Bengali script (LTR)
├── audio/
│   ├── ar-SA/
│   │   ├── scene_1.mp3          # Synthesized scene voiceover
│   │   └── scene_2.mp3
│   └── bn-BD/
├── avatars/
│   ├── ar-SA/
│   │   └── scene_1.mp4          # HeyGen or Mock talking-head video
│   └── bn-BD/
├── visuals/
│   ├── ar-SA/
│   │   └── scene_1.png          # 1920x1080 Full HD slide graphics
│   └── bn-BD/
├── subtitles/
│   ├── ar-SA/
│   │   ├── subtitles.srt        # SubRip text format
│   │   └── subtitles.vtt        # WebVTT format
│   └── bn-BD/
├── rendered/
│   ├── ar-SA/
│   │   ├── scene_1.mp4          # Composite scene video (avatar/visual + audio + subtitles)
│   │   └── scene_2.mp4
│   └── bn-BD/
└── final/
    ├── training_ar-SA.mp4       # Final concatenated training video
    └── training_bn-BD.mp4
```

---

## 4. Pipeline State Machine & Execution Flow

1. **`pending`**: Project manifest initialized (`POST /api/v1/projects`).
2. **`running (script)`**: LangGraph canonical workflow (`normalize_input` -> `analyze_content` -> `generate_script` -> `validate_script` -> `finalize_script`).
3. **`running (localization)`**: `LocalizationService` translates and adapts scripts per target locale (`ar-SA`, `bn-BD`), recording cultural guidance.
4. **`running (audio)`**: `TTSService` synthesizes speech for every scene and updates script scenes with ground-truth measured duration via `get_audio_duration()`.
5. **`running (avatar)`**: `AvatarService` evaluates `is_avatar_eligible(scene)` and generates talking-head video segments for eligible scenes.
6. **`running (visuals)`**: `VisualService` renders 1920x1080 Pillow graphic cards with accent bars, badges, and Unicode typography.
7. **`running (subtitles)`**: `SubtitleService` chunks narration text proportionally against the exact audio duration to produce monotonic subtitle cues.
8. **`running (composition)`**: `CompositionService` renders per-scene MP4 files using FFmpeg (with subtitle burn-in) and performs ordered concatenation.
9. **`completed`**: All target locales rendered successfully; manifest updated with output file paths.
10. **`needs_review` / `failed`**: If validation or non-recoverable errors occur, errors are isolated in manifest without deleting prior valid stages.
