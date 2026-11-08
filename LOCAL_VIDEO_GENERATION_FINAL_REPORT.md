# LOCAL VIDEO GENERATION PIPELINE — FINAL AUDIT & ACCEPTANCE REPORT

**Project:** AI Multilingual Training Video Generator  
**Execution Mode:** Local Only — Zero Paid API Calls  
**Primary Avatar Engine:** SadTalker Local (Isolated Runtime, CUDA GPU-Accelerated)  
**Target Locale:** `ar-SA` (Arabic — Saudi Arabia)  
**Target Duration:** 30.0 seconds  
**Accepted Final Duration:** 30.42 seconds (Overrun: +0.42s, within ±2.0s tolerance)  
**Final Test Status:** **255 Passed (0 Failed, 0 Errors)**  
**Date:** 2026-10-08  

---

## 1. Executive Summary

This report documents the finalization, production hardening, and successful real end-to-end acceptance testing of the completely **free and local** multilingual training video generation pipeline.

The system takes an instructional topic in English, generates a pedagogically sound canonical script using Groq (`openai/gpt-oss-20b`), translates and culturally adapts the script into Saudi Arabic (`ar-SA`), synthesizes realistic voice narration via Edge-TTS, deterministically reconciles duration drift back to the target budget (30s) in a dedicated service, animates a high-resolution local portrait using an isolated SadTalker model on an NVIDIA GeForce RTX 4060 GPU, produces professional supporting visual slides, burns in complex RTL HarfBuzz Arabic subtitles, and renders a normalized 1920x1080 48kHz stereo MP4 video via FFmpeg.

All work has been executed locally with zero calls to paid external avatar APIs (HeyGen) and zero wallet consumption.

---

## 2. Final Architecture

```
User Training Request
        │
        ▼
Groq Script Engine (openai/gpt-oss-20b)
        │
        ▼
Localization Pipeline (ar-SA Cultural & RTL Adaptation)
        │
        ▼
Speech Synthesis Engine (Edge-TTS ar-SA-HamedNeural)
        │
        ▼
Authoritative Audio Waveform Measurement (ffprobe)
        │
        ▼
Duration Reconciliation Service (app/services/duration/)
   ├── Overrun Detection (measured > target ± tolerance)
   ├── Proportional Scene Budget Allocation
   ├── Pedagogical Condensation (Groq Structured Prompt)
   └── Re-synthesis & Waveform Verification (Round 1: 42.29s -> 30.41s)
        │
        ▼
Duration Approval Gate
        │
   ┌────┴──────────────────────────┐
   ▼                               ▼
SadTalker Local Avatar Engine   Local Visual Slides Engine
(Intro & Outro via CUDA)        (Core Explanation Slides)
   │                               │
   └──────────────┬────────────────┘
                  ▼
Deterministic Subtitle Engine (ASS with HarfBuzz RTL Shaping)
                  ▼
FFmpeg Scene Rendering (Audio Normalized to 48kHz Stereo AAC 192kbps)
                  ▼
FFmpeg Concatenation & Container Assembly
                  ▼
Final Multilingual Video (1920x1080, 25 FPS, 30.42s MP4)
```

---

## 3. Provider Matrix

| Stage | Default / Active Provider | Secondary / Alternative | Isolation / Licensing |
| :--- | :--- | :--- | :--- |
| **LLM** | `groq` (`openai/gpt-oss-20b`) | Extensible to local Ollama / OpenAI | Cloud Free/Paid Tier |
| **TTS** | `edge_tts` (`ar-SA-HamedNeural`) | `azure`, `mock` | Free Edge API |
| **Avatar** | `sadtalker` (Local Free) | `mock`, `heygen` (Paid API) | Isolated `.sadtalker-venv`, `CC BY-NC 4.0` |
| **Visuals**| `local` (Pillow / Matplotlib) | Extensible slide renderers | Free Local |
| **Subtitles** | `deterministic` (SRT, VTT, ASS) | Whisper / Speech-to-text | Free Local |
| **Composition** | `ffmpeg` (Subprocess) | MoviePy | Free Local |

---

## 4. Groq Configuration

- **Provider:** `GroqProvider` (`app/services/llm/groq_provider.py`)
- **Active Model ID:** `openai/gpt-oss-20b` (per settings `GROQ_MODEL`)
- **System Guardrails:** Structured output parsing via Pydantic schemas (`ContentAnalysis`, `ScriptDraft`, `LocalizedScript`).
- **Resilience:** Exponential backoff retry handler catching HTTP 429 rate limits automatically.

---

## 5. TTS Configuration

- **Provider:** `EdgeTTSProvider` (`app/services/tts/edge_tts_provider.py`)
- **Voice Selected:** `ar-SA-HamedNeural` (natural, authoritative Saudi Arabic narration)
- **Audio Output:** Single-channel MP3 intermediate assets measured authoritatively on disk before feeding downstream video systems.

---

## 6. SadTalker Isolation Design

To maintain long-term stability and eliminate dependency conflicts between modern Python 3.13 packages (FastAPI, Pydantic v2, PyTorch 2.6+) and SadTalker requirements:
- **Main App Runtime:** Python 3.13.5 in `.venv`.
- **SadTalker Runtime:** Python 3.10.18 with CUDA 11.8 PyTorch in `.sadtalker-venv/`.
- **Communication:** Subprocess execution via `SadTalkerProvider` using explicit lists of arguments (never `shell=True`).
- **Checkpoints Directory:** `tools/sadtalker/checkpoints/` (contains `SadTalker_V0.0.2_256.safetensors`, `mapping_00229-model.pth.tar`, `mapping_00109-model.pth.tar`).
- **Presenter Source Image:** Project-owned portrait `assets/avatars/local_presenter.png`.

---

## 7. Duration Reconciliation Design

Refactored from `LocalizationService` into dedicated module `app/services/duration/`:
- **Files:** `models.py`, `reconciliation.py`.
- **Tolerance:** Configurable via `POST_TTS_DURATION_TOLERANCE_SECONDS=2.0`.
- **Maximum Revisions:** Configurable via `MAX_POST_TTS_REVISIONS=2`.
- **Budgeting Formula:** Proportional weighting ($w_{\text{intro}}=0.8$, $w_{\text{explanation}}=1.0$, $w_{\text{outro}}=0.8$).
- **Content Invariance:** Preserves scene IDs, sequence, learning objective IDs, and cultural terminology.

---

## 8. Cache Invalidation Architecture

Content-aware cache invalidation implemented in `app/core/caching.py`:
- Tracks sidecar `.meta.json` files storing SHA-256 hashes of narration text, voice ID, source image, audio files, and layout parameters.
- If narration changes during post-TTS reconciliation, downstream audio, avatar MP4s, subtitles, rendered scenes, and final videos are systematically invalidated and regenerated.

---

## 9. Subtitle Architecture

- **Engine:** `DeterministicSubtitleProvider` and `SubtitleService`.
- **Formats Generated:** `.srt`, `.vtt`, and `.ass`.
- **Complex RTL Shaping:** Substation Alpha (.ass) subtitles rendered with libass and HarfBuzz complex shaping.
- **Presenter Collision Avoidance:** Subtitles positioned with safe bottom margins avoiding overlap with the presenter picture-in-picture box.

---

## 10. Composition Architecture

- **Layout:** High-resolution 1920x1080 canvas.
- **Presenter PiP:** Rendered at 540x540 in the bottom-right corner with 24px padding and a subtle border.
- **Visuals:** Left side supporting slide graphic and key takeaway text.
- **Duration Matching:** Presenter video safely trimmed/padded to exact audio duration without pitch distortion.

---

## 11. Audio Normalization Fix

Historical timeline drift (~66.31s composition for ~44s audio) was caused by concatenating heterogeneous audio sample rates from different source streams.
- **Current Standard:** All rendered scenes normalize audio to:
  - **Sample Rate:** `48,000 Hz`
  - **Channels:** `Stereo (2 channels)`
  - **Codec:** `AAC`
  - **Bitrate:** `192 kbps`
- **Waveform Authority:** The clean Edge-TTS audio is passed directly to FFmpeg as the authoritative audio track, preventing degraded avatar-generated audio from corrupting the final master.

---

## 12. Historical Issues Fixed

| Issue Code | Description | Status |
| :--- | :--- | :---: |
| **ISSUE-001** | Script generation pipeline failure & diagnostic swallowing | **RESOLVED** |
| **ISSUE-002** | Avatar engine locked in Mock mode without UI control | **RESOLVED** |
| **ISSUE-003** | Hardcoded LLM model label in Streamlit sidebar | **RESOLVED** |
| **ISSUE-004** | Manifest diagnostic error duplication on retries | **RESOLVED** |
| **ISSUE-005** | Base-language & source-content decoupling | **RESOLVED** |
| **ISSUE-006** | Audio duration estimation drift | **RESOLVED** |
| **ISSUE-007** | Subtitle track desynchronization | **RESOLVED** |
| **ISSUE-008** | Incomplete E2E pipeline verification | **RESOLVED** |
| **TIMING-001** | 66.31s audio sample rate mismatch bug | **RESOLVED** |
| **DURATION-001** | 41.88s duration overshoot vs 30s target | **RESOLVED** |

---

## 13. Tests

- **Pytest Baseline:** 219 passed
- **New Tests Added:** 36 tests in `tests/test_master_local_pipeline.py`
- **Total Test Count:** **255 passed**
- **Test Failures:** **0**
- **Test Errors:** **0**
- **Execution Time:** ~74.86 seconds

---

## 14. Acceptance E2E Results

A clean, live end-to-end acceptance test was executed on project `proj_local_video_generation_acceptance`:
- **Topic:** Phishing Email Awareness for Employees
- **Base Language:** `en-US`
- **Target Locale:** `ar-SA`
- **Requested Duration:** `30.00s`
- **Initial TTS Measured:** `42.29s`
- **Reconciliation:** Triggered Revision 1 (compression ratio: `0.7094`)
- **Revised TTS Measured:** `30.41s`
- **Duration Approval:** Granted (Revision 1, $+0.41\text{s}$ diff)
- **SadTalker Synthesis:** Generated scene 1 (intro) and scene 4 (outro)
- **Local Visuals:** Generated scene 2 and scene 3 (explanation slides)
- **FFmpeg Master Composition:** Generated `training_ar-SA.mp4` in `30.42s`
- **Difference:** $+0.42\text{s}$ (within $\pm2.0\text{s}$ tolerance)

---

## 15. Scene Timeline Audit Table

```
========================================================================================================
Scene      | Type         | Words | Target  | Initial TTS | Final TTS | Avatar / Vis | Rendered | Sub End 
--------------------------------------------------------------------------------------------------------
scene_1    | intro        | 11    | 6.0s    | 8.95s       | 6.41s     | SadTalker    | 6.40s    | 6.41s   
scene_2    | explanation  | 12    | 9.0s    | 12.34s      | 8.98s     | Visual Slide | 8.98s    | 8.98s   
scene_3    | explanation  | 14    | 8.0s    | 11.78s      | 8.18s     | Visual Slide | 8.18s    | 8.18s   
scene_4    | outro        | 10    | 7.0s    | 9.22s       | 6.84s     | SadTalker    | 6.84s    | 6.84s   
--------------------------------------------------------------------------------------------------------
Total Requested: 30.00s
Sum Final TTS:   30.41s
Sum Rendered:    30.40s
Final MP4:       30.42s (Container / audio precision difference: 0.02s)
Overrun vs Goal: +0.42s (1.4% error)
========================================================================================================
```

---

## 16. Final Duration

- **Requested Target:** `30.00 seconds`
- **Initial TTS:** `42.29 seconds`
- **Final Approved TTS:** `30.41 seconds`
- **Final Rendered MP4:** `30.42 seconds`
- **Error:** `+0.42 seconds` (Passes default $\pm2.0\text{s}$ tolerance criteria).

---

## 17. Final MP4 Metadata (`ffprobe`)

- **File Path:** `storage/projects/proj_local_video_generation_acceptance/final/training_ar-SA.mp4`
- **File Size:** `1,302,061 bytes` (1.24 MB)
- **Exact Duration:** `30.417333 seconds`
- **Resolution:** `1920 x 1080` (Full HD)
- **Frame Rate:** `25.0 fps` (`25/1`)
- **Video Codec:** `h264` (`High Profile, yuv420p`)
- **Audio Codec:** `aac` (LC)
- **Audio Sample Rate:** `48,000 Hz`
- **Audio Channels:** `2` (Stereo)
- **Audio Bitrate:** `167,955 bps`

---

## 18. SadTalker Performance

- **Hardware GPU:** NVIDIA GeForce RTX 4060 Laptop GPU (8,188 MiB VRAM)
- **Scene 1 (Intro):**
  - Footage Duration: `6.40 seconds`
  - Inference Time: `35.91 seconds`
  - Real-Time Factor (RTF): `5.61x`
- **Scene 4 (Outro):**
  - Footage Duration: `6.84 seconds`
  - Inference Time: `37.40 seconds`
  - Real-Time Factor (RTF): `5.47x`
- **Total Avatar Footage:** `13.24 seconds`
- **Total Avatar Inference:** `73.31 seconds`
- **Overall Average RTF:** `5.54x` (Inference time / Video duration)

---

## 19. Human-Review Notes

1. **Arabic Pronunciation & Cadence:** Edge-TTS `ar-SA-HamedNeural` delivers natural, accent-accurate formal Arabic pronunciation for cybersecurity terminology.
2. **Lip Synchronization:** SadTalker mouth movements match the Arabic spoken syllables with realistic jaw articulation.
3. **Presenter Framing:** The PiP layout (540x540 bottom-right) avoids the blurring associated with fullscreen upscaling of 256x256 native neural output.
4. **Visual Slides & Subtitles:** Clean Arabic HarfBuzz typography with right-to-left flow and zero overlapping artifacts.
5. **Pacing:** Pacing is brisk and professional; post-TTS condensation successfully removed discursive fluff while maintaining all security directives.

---

## 20. Remaining Limitations

1. **SadTalker Head Movement:** While `--still` mode eliminates erratic neck swings, subtle head movements remain somewhat synthetic compared to multi-gigabyte diffusion models (e.g. MuseTalk or proprietary HeyGen engines).
2. **GPU Prerequisite:** SadTalker requires an NVIDIA GPU with at least 6GB VRAM for practical inference times (~5.5x RTF). On CPU, inference time slows down to ~25–40x RTF.
3. **Commercial Licensing:** SadTalker's upstream checkpoints are licensed under `CC BY-NC 4.0`. Commercial enterprise deployments require commercial licensing or migration to an open commercial pipeline.

---

## 21. HeyGen Status

- **Codebase Support:** Fully preserved in `HeyGenProvider` (`app/services/avatar/heygen_provider.py`).
- **Safety Flags:** Protected by `ENABLE_LIVE_HEYGEN` and `ack_paid_credits` flags.
- **Calls During This Task:** **0**
- **Paid Credits Consumed:** **0**

---

## 22. Cost

- **HeyGen API Calls:** 0
- **HeyGen Paid Credits:** 0
- **Total External Avatar Cost:** **$0.00 (Completely Free Local Generation)**
