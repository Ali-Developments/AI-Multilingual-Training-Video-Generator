# VIDEO AUTOMATION — AUTONOMOUS BUILD MASTER PLAN

> **Purpose:** This file is the single source of execution instructions for continuing the AI-powered multilingual training video generation project without requiring step-by-step human prompting.
>
> **Current project status:** Steps 1–4 are already implemented and tested. Continue from **Step 5**.
>
> **Core product goal:** Convert a training/educational topic or source content into a validated multilingual video package containing localized scripts, generated speech, talking-avatar segments, subtitles, supporting visuals, and a final composed training video.

---

# 0. AUTONOMOUS EXECUTION MODE

From this point onward, work autonomously.

Do **not** wait for human approval after each step unless you encounter a true blocker that cannot be safely handled by mocks, configuration, or a local fallback.

For every remaining step, follow this cycle:

1. Inspect the existing implementation.
2. Read relevant schemas, services, tests, and `ARCHITECTURE.md`.
3. Confirm existing behavior before changing anything.
4. Implement only the current step.
5. Run targeted tests for the new step.
6. Run the **complete project test suite**.
7. Perform a self-review.
8. Fix every issue found.
9. Re-run tests.
10. Update documentation.
11. Record progress in `AUTONOMOUS_PROGRESS.md`.
12. Move to the next step automatically if the quality gate passes.

Do not ask for permission between steps.

---

# 1. NON-NEGOTIABLE PROJECT RULES

## 1.1 Preserve Working Architecture

Do not rewrite completed working modules without a concrete technical reason.

Existing abstractions are intentional:

- `LLMProvider`
- `GroqProvider`
- deterministic Step 3 script workflow
- localization service from Step 4
- Pydantic contracts
- configuration-driven providers
- deterministic validation
- mocked unit tests

Extend the architecture rather than bypassing it.

## 1.2 Vendor Abstraction

All external capabilities must have interfaces/providers.

Examples:

```text
LLMProvider
    └── GroqProvider

TTSProvider
    ├── EdgeTTSProvider
    └── MockTTSProvider

AvatarProvider
    ├── HeyGenProvider
    └── MockAvatarProvider

SubtitleProvider
    ├── DeterministicSubtitleProvider
    └── optional FasterWhisperProvider

VisualAssetProvider
    ├── LocalVisualProvider
    └── optional future providers
```

Business/workflow code must not directly depend on vendor SDKs.

## 1.3 API Cost Safety

Default behavior must consume **zero paid API credits** during development/tests.

Never make real paid API calls automatically.

Especially:

- HeyGen
- Azure Speech
- ElevenLabs
- paid image APIs
- other paid external providers

Live external integration is allowed only when all of the following are true:

1. credentials exist;
2. the project explicitly enables live execution through configuration;
3. the action is clearly separated from normal unit tests.

Recommended safety configuration:

```env
ENABLE_LIVE_API_TESTS=false
```

All automated tests must remain mock-based by default.

A missing external API key must **not** block project development.

Implement the provider, mock it, test it, document the live requirement, and continue.

## 1.4 Secrets

Never:

- hardcode API keys;
- print API keys;
- include API keys in reports;
- commit `.env`;
- copy secrets into test fixtures.

Use environment configuration only.

## 1.5 Test Discipline

Every feature must be tested.

Required order:

```text
new targeted tests
        ↓
existing related tests
        ↓
complete pytest suite
```

A step may only be marked complete when:

```text
0 failed
0 errors
```

Warnings must be reviewed rather than ignored blindly.

## 1.6 Self-Repair Policy

When tests fail:

1. inspect the root cause;
2. fix the implementation;
3. rerun the smallest relevant test;
4. rerun the complete suite;
5. repeat until green.

Do not weaken tests merely to force them to pass.

Do not remove legitimate validation rules just because generated mock data fails.

## 1.7 Source of Truth

Use deterministic Python calculations for values that can be calculated.

Examples:

- duration from narration;
- total duration from scene durations;
- protected scene IDs;
- scene order;
- learning-objective IDs;
- locale normalization;
- output paths;
- asset manifests.

Do not trust an LLM to preserve identifiers or calculate deterministic metadata.

## 1.8 Windows Compatibility

Primary development environment is Windows.

All filesystem code must use `pathlib`.

Never hardcode slash direction.

Avoid shell-only assumptions that work on Linux but fail on Windows.

---

# 2. COMPLETED FOUNDATION — DO NOT REBUILD

## STEP 1 — PROJECT FOUNDATION — COMPLETED

Expected existing components include:

- FastAPI application
- configuration via Pydantic Settings
- structured logging
- API v1 structure
- health endpoint
- Streamlit skeleton
- storage directories
- `.env.example`
- `.gitignore`
- project documentation
- automated tests

Do not rebuild Step 1.

## STEP 2 — LLM SERVICE — COMPLETED

Expected architecture:

```text
LLMProvider
    └── GroqProvider
```

Requirements already established:

- model configured via `GROQ_MODEL`
- default development model currently `openai/gpt-oss-20b`
- no hardcoded model ID inside provider
- structured Pydantic output
- retry/backoff
- factory
- mockable client
- no network calls in unit tests

Do not bypass this abstraction.

## STEP 3 — VIDEO-READY SCRIPT WORKFLOW — COMPLETED

Expected conceptual flow:

```text
TrainingVideoRequest
        ↓
normalize_input
        ↓
analyze_content
        ↓
generate_script
        ↓
validate_script
        ↓
revision if needed
        ↓
FinalScript
```

`FinalScript` scenes contain production metadata such as:

- `scene_id`
- `order`
- `title`
- `purpose`
- `narration`
- `estimated_duration_seconds`
- `visual_direction`
- `on_screen_text`
- `learning_objective_ids`
- `scene_type`

Duration is deterministic:

```python
words = len(narration.split())
duration = max(2, round((words / SCRIPT_WORDS_PER_MINUTE) * 60))
```

The LLM must not control final duration metadata.

## STEP 4 — LOCALIZATION & CULTURAL ADAPTATION — COMPLETED

Expected architecture:

```text
FinalScript
      ↓
LocalizationService
      ├── ar-SA → LocalizedScript
      ├── bn-BD → LocalizedScript
      └── ...
      ↓
LocalizationBundle
```

Protected fields remain aligned across locales:

- `scene_id`
- `order`
- `scene_type`
- `learning_objective_ids`

Localization may adapt:

- narration
- titles
- purpose
- visual direction
- on-screen text
- learning-objective descriptions
- cultural presentation metadata

Source `FinalScript` must remain immutable.

Localization duration is recalculated from localized narration.

---

# 3. PRE-STEP-5 BASELINE CHECK

Before implementing Step 5:

1. Run the complete test suite.
2. Confirm the completed Step 1–4 tests remain green.
3. Inspect:
   - `app/models/schemas.py`
   - `app/core/config.py`
   - `app/services/llm/`
   - `app/workflows/script_generation/`
   - `app/services/localization/`
   - `ARCHITECTURE.md`
4. Create or update `AUTONOMOUS_PROGRESS.md`.
5. Record baseline test count.

If existing tests fail before Step 5:

- fix regression/environment issues first;
- do not continue until baseline is green.

---

# 4. STEP 5 — TTS & EXACT AUDIO DURATION

## Objective

Generate isolated speech audio for every localized scene and replace approximate pre-TTS duration with actual audio duration.

The audio output becomes the timing ground truth for later:

- avatar generation;
- subtitle synchronization;
- final composition.

## 4.1 TTS Architecture

Create:

```text
TTSProvider (abstract)
    ├── EdgeTTSProvider
    └── MockTTSProvider
```

Keep provider architecture open for future:

- Azure
- ElevenLabs
- local/offline engines

Do not couple workflows directly to Edge TTS.

## 4.2 TTS Input

Consume `LocalizedScript`.

Each scene must be synthesized independently.

Example paths:

```text
storage/
  projects/
    <project_id>/
      audio/
        ar-SA/
          scene_1.mp3
          scene_2.mp3
        bn-BD/
          scene_1.mp3
          scene_2.mp3
```

Use `pathlib`.

## 4.3 Audio Manifest Models

Add clean schemas, for example:

```text
SceneAudioAsset
- scene_id
- locale
- audio_path
- duration_seconds
- provider
- voice_id
- status

LocalizedAudioTrack
- locale
- scene_audio
- total_audio_duration_seconds
```

Do not put raw provider client objects inside models.

## 4.4 Voice Configuration

Voice selection must be configuration-driven.

Never hardcode one voice inside the provider.

Allow locale-to-voice configuration.

If no locale-specific voice is configured, use a provider-supported default resolution strategy.

Keep gender/style preferences optional metadata, not assumptions.

## 4.5 Edge TTS

Implement Edge TTS as the default low-cost/free development provider if compatible with the environment.

Requirements:

- async-safe integration;
- timeout handling;
- clear errors;
- output file validation;
- empty-file detection;
- configurable voice;
- testable without network.

Do not call the real service inside unit tests.

## 4.6 Exact Audio Duration

After generation, determine actual audio duration from the generated media file.

Use a reliable local method.

Do not infer real duration from word count after TTS exists.

Store the measured value as timing truth.

## 4.7 Failure Isolation

If one scene fails:

- record the scene error;
- do not silently mark the entire locale successful;
- preserve already generated successful scene assets.

If one locale fails, other locales may continue.

## 4.8 Idempotency

If a valid audio asset already exists and its manifest indicates completion:

- do not regenerate unnecessarily unless explicitly forced.

Support `force_regenerate=False` or equivalent.

## 4.9 Step 5 Tests

Test at minimum:

1. provider abstraction;
2. mock provider;
3. voice configuration;
4. per-scene file path construction;
5. Windows-safe path logic;
6. one audio asset per scene;
7. actual duration reading;
8. total duration equals sum of audio durations;
9. missing narration fails clearly;
10. empty generated file rejected;
11. scene failure isolation;
12. locale failure isolation;
13. existing completed asset reused;
14. force regeneration;
15. no live TTS call in unit tests;
16. all previous tests still pass.

## Step 5 Completion Gate

Do not continue until the full test suite passes.

Then document:

- TTS architecture;
- timing ground truth;
- voice configuration;
- output structure;
- failures;
- tests.

---

# 5. STEP 6 — HEYGEN AVATAR INTEGRATION

## Objective

Create avatar video segments for presenter-type scenes using HeyGen while keeping vendor details behind an `AvatarProvider`.

## 5.1 Architecture

Create:

```text
AvatarProvider
    ├── HeyGenProvider
    └── MockAvatarProvider
```

Workflow/service code must only know `AvatarProvider`.

## 5.2 Scene Eligibility

Do not blindly send every scene to HeyGen.

Define deterministic behavior based on scene metadata.

Examples:

- `presenter` → avatar may be appropriate;
- `explanation` → configurable;
- `visual_demo` → may not require avatar;
- `intro/outro` → configurable.

Create a helper such as `requires_avatar(scene)`.

## 5.3 HeyGen Configuration

All IDs/configuration must be externalized.

Examples:

```env
HEYGEN_API_KEY=
HEYGEN_DEFAULT_AVATAR_ID=
HEYGEN_DEFAULT_VOICE_ID=
HEYGEN_POLL_INTERVAL_SECONDS=
HEYGEN_JOB_TIMEOUT_SECONDS=
```

No provider IDs hardcoded in business logic.

## 5.4 Cultural Guidance

Step 4 generated cultural metadata.

Use it as guidance for future avatar selection, but do not make unsafe or stereotypical assumptions.

Locale must not automatically imply:

- religion;
- ethnicity;
- gender;
- traditional clothing.

Avatar configuration may be explicitly mapped by the user/project.

## 5.5 Audio-Driven Avatar

Where supported, use Step 5 generated audio as the narration source so timing remains aligned.

Do not regenerate independent narration inside HeyGen when that would create timing mismatch.

## 5.6 Async Job Handling

HeyGen integration must support:

```text
submit
→ receive job ID
→ poll status
→ completed / failed / timed out
→ retrieve result
```

Implement:

- timeout;
- retry for safe transient failures;
- rate-limit handling;
- invalid-key handling;
- failed-job handling;
- clear structured exceptions.

## 5.7 Local Mock Mode

All tests use `MockAvatarProvider`.

Never consume HeyGen credits in normal test runs.

If `ENABLE_LIVE_API_TESTS=false`, no live HeyGen call is permitted.

## 5.8 Asset Model

Example:

```text
AvatarVideoAsset
- scene_id
- locale
- provider
- job_id
- video_path / remote_url
- duration_seconds
- status
- avatar_id
```

Provider-specific raw payloads should not become core domain contracts.

## 5.9 Step 6 Tests

Test:

1. provider abstraction;
2. mock provider;
3. scene avatar eligibility;
4. job submission;
5. status polling;
6. completion;
7. provider failure;
8. timeout;
9. rate-limit retry;
10. configuration loading;
11. no hardcoded avatar IDs;
12. audio asset correctly associated with scene;
13. scene/locale alignment;
14. no live HeyGen calls in unit tests;
15. previous tests still pass.

---

# 6. STEP 7 — SUBTITLE GENERATION

## Objective

Generate accurate subtitle assets aligned to the Step 5 TTS audio.

## 6.1 Architecture

Create:

```text
SubtitleProvider
    ├── DeterministicSubtitleProvider
    └── optional FasterWhisperProvider
```

Do not require a paid subtitle API.

## 6.2 MVP Strategy

Because narration text is already known, do not unnecessarily retranscribe everything unless useful.

Preferred approach:

1. take known localized narration;
2. use exact audio duration;
3. split into readable subtitle chunks;
4. assign timing deterministically/proportionally;
5. preserve punctuation/readability;
6. optionally support Faster-Whisper later for timestamp refinement.

The pipeline must work without Whisper.

## 6.3 Formats

Generate at minimum:

- `.srt`

Prefer also:

- `.vtt`

Use UTF-8.

Arabic and Bengali text must remain intact.

## 6.4 Subtitle Rules

Avoid:

- extremely long single captions;
- zero-length captions;
- overlapping timestamps;
- timestamps beyond scene duration.

Ensure:

```text
start < end
next.start >= previous.end
last.end <= audio duration
```

## 6.5 Scene-Level Assets

Example:

```text
subtitles/
  ar-SA/
    scene_1.srt
    scene_2.srt
```

## 6.6 RTL Metadata

Preserve direction metadata for future rendering.

Do not attempt complex font rendering in this step.

## 6.7 Step 7 Tests

Test:

1. sentence/chunk splitting;
2. timing monotonicity;
3. no overlap;
4. final timestamp within audio duration;
5. SRT serialization;
6. VTT serialization;
7. UTF-8 Arabic;
8. UTF-8 Bengali;
9. None/empty narration handling;
10. per-scene path creation;
11. no external API dependency;
12. previous tests pass.

---

# 7. STEP 8 — SUPPORTING VISUAL ASSET PIPELINE

## Objective

Create supporting visuals for non-avatar portions of the training video.

The baseline implementation must work locally without requiring paid image APIs.

## 7.1 Architecture

Create:

```text
VisualAssetProvider
    ├── LocalVisualProvider
    └── future optional image providers
```

## 7.2 Local Baseline

Build a reliable local visual baseline using open-source/local libraries.

Possible outputs:

- title cards;
- concept slides;
- bullet slides;
- quote/callout cards;
- simple diagrams;
- background cards;
- scene labels;
- branded intro/outro visuals.

Use local/open-source rendering tools.

Do not make the working product depend on an external image-generation API.

## 7.3 Visual Direction Consumption

Consume:

- `visual_direction`
- `on_screen_text`
- `scene_type`

Map them to local visual templates.

Do not interpret arbitrary text as executable code.

## 7.4 Optional Generated Images

If adding future AI-image support:

- keep it provider-based;
- keep it optional;
- do not block MVP;
- do not call paid APIs automatically.

## 7.5 Cultural Metadata

Cultural guidance may inform:

- office/environment style;
- formality;
- textual presentation.

Avoid stereotypes.

Do not infer protected personal attributes.

## 7.6 Step 8 Tests

Test:

1. provider abstraction;
2. correct output dimensions;
3. valid image creation;
4. Arabic/Bengali Unicode handling;
5. missing optional text;
6. deterministic output paths;
7. one visual asset per eligible scene;
8. cultural metadata does not alter protected scene IDs;
9. no paid external calls;
10. previous tests pass.

---

# 8. STEP 9 — VIDEO COMPOSITION WITH FFMPEG

## Objective

Compose final scene videos and final multilingual training videos.

Use FFmpeg as the primary media engine.

## 8.1 Composition Inputs

Potential scene inputs:

- TTS audio;
- HeyGen avatar video;
- supporting visual asset;
- subtitles;
- intro/outro;
- on-screen text;
- transitions.

## 8.2 FFmpeg First

Prefer direct FFmpeg orchestration.

Avoid introducing MoviePy unless it solves a concrete need.

Verify FFmpeg availability during startup/health checks.

Provide a clear message if it is missing.

## 8.3 Scene Renderer

Create a scene rendering service.

For each scene determine layout.

### Avatar scene

```text
avatar video
+ optional supporting visual
+ subtitle layer
+ optional title/on-screen text
```

### Visual-only scene

```text
supporting visual
+ audio
+ subtitles
+ optional motion/transition
```

## 8.4 Timing

The Step 5 audio duration is the timing source of truth.

Do not stretch audio arbitrarily to match old script estimates.

Visual/video assets should adapt to audio timing.

## 8.5 Output Settings

Create configurable defaults such as:

```text
VIDEO_WIDTH=1920
VIDEO_HEIGHT=1080
VIDEO_FPS=30
VIDEO_CODEC=h264
AUDIO_CODEC=aac
```

Do not scatter magic values.

## 8.6 Final Concatenation

Render scene outputs, then concatenate in `order`.

Example:

```text
rendered/
  ar-SA/
    scene_1.mp4
    scene_2.mp4
    final_ar-SA.mp4
```

## 8.7 Subtitle Strategy

Support at least:

- burned-in subtitles;
- optionally sidecar subtitles.

RTL text rendering must be tested.

If font rendering requires a user-provided font, configure it rather than bundling proprietary fonts.

## 8.8 Step 9 Tests

Use small synthetic assets.

Test:

1. FFmpeg detection;
2. simple audio+image render;
3. scene output exists;
4. output duration approximately matches audio;
5. concatenation order;
6. final video exists;
7. valid video metadata;
8. subtitle inclusion;
9. failure on missing required asset;
10. cleanup behavior;
11. Windows-safe commands;
12. previous tests pass.

Do not require HeyGen live output for tests.

---

# 9. STEP 10 — FULL END-TO-END PROJECT ORCHESTRATION

## Objective

Connect all completed stages into one project pipeline.

## 9.1 End-to-End Flow

```text
TrainingVideoRequest
        ↓
Script Workflow
        ↓
FinalScript
        ↓
Localization
        ↓
LocalizationBundle
        ↓
TTS
        ↓
Audio Assets
        ↓
Avatar Generation
        ↓
Supporting Visuals
        ↓
Subtitles
        ↓
Scene Composition
        ↓
Final Videos
```

## 9.2 Project Manifest

Create a persistent local manifest such as `project.json`.

Suggested information:

```text
project_id
created_at
updated_at
status
source_request
script_status
localization_status
audio_status
avatar_status
subtitle_status
visual_status
composition_status
outputs
errors
```

This must allow resuming work without recomputing everything.

## 9.3 Pipeline Status

Suggested states:

```text
pending
running
completed
needs_review
failed
skipped
```

## 9.4 Idempotency

Re-running a completed project should reuse successful artifacts.

Only regenerate what is:

- missing;
- invalid;
- explicitly forced.

## 9.5 Error Isolation

A single locale failing should not delete successful locale results.

A scene failing should preserve completed earlier assets.

## 9.6 Resume Capability

Implement restart/resume logic from the manifest.

If script/localization/audio are completed but HeyGen was unavailable, resume from avatar generation.

Do not regenerate scripts unnecessarily.

## 9.7 Mock End-to-End Test

Implement a complete E2E test using:

- Mock LLM
- Mock TTS
- Mock Avatar
- local subtitle generation
- local visuals
- FFmpeg synthetic composition if available

No paid API calls.

---

# 10. STEP 11 — FASTAPI ENDPOINTS

## Objective

Expose the pipeline through a stable backend API.

## 10.1 Suggested Endpoints

```text
POST /api/v1/projects
GET  /api/v1/projects/{project_id}
POST /api/v1/projects/{project_id}/run
POST /api/v1/projects/{project_id}/resume
GET  /api/v1/projects/{project_id}/outputs
```

Avoid unnecessary endpoint proliferation.

## 10.2 Request Validation

Use Pydantic schemas.

Reject malformed inputs clearly.

Return structured errors.

Never expose:

- stack traces;
- secrets;
- provider credentials.

## 10.3 Long Operations

Keep pipeline execution logic separated from HTTP handlers so background processing can be added later.

Do not add Celery unless needed.

---

# 11. STEP 12 — STREAMLIT USER INTERFACE

## Objective

Provide an MVP frontend capable of creating and inspecting generated training-video projects.

## 11.1 Input UI

Support:

- topic;
- source content;
- audience;
- base language;
- target locales;
- target duration;
- tone;
- difficulty;
- learning objectives.

## 11.2 Review Panels

Display:

- generated canonical script;
- localized scripts;
- scene breakdown;
- cultural guidance;
- audio status;
- avatar status;
- subtitle status;
- final video status.

## 11.3 Controls

Allow:

- create project;
- run pipeline;
- retry failed locale/scene;
- regenerate selected asset;
- preview outputs;
- download final output.

Do not expose API secrets in the UI.

## 11.4 Graceful Missing Providers

If HeyGen credentials are unavailable, show that mock/development mode is active.

Do not crash the entire app.

---

# 12. STEP 13 — RELIABILITY, VALIDATION & HARDENING

## Objective

Perform an internal engineering audit before declaring the project complete.

## 12.1 Full Static Review

Inspect for:

- dead imports;
- duplicate models;
- duplicate duration formulas;
- direct vendor SDK leaks;
- hardcoded paths;
- hardcoded model IDs;
- hardcoded avatar IDs;
- secrets;
- TODOs accidentally left in critical paths;
- unhandled exceptions;
- mutable default arguments;
- weak typing;
- circular imports.

Fix issues.

## 12.2 Failure Scenarios

Test:

- missing Groq key;
- missing HeyGen key;
- network timeout;
- rate limiting;
- malformed LLM JSON;
- TTS failure;
- missing FFmpeg;
- corrupted audio;
- corrupted video;
- invalid locale;
- one failed locale among multiple successful locales;
- incomplete project resume.

## 12.3 Security Review

Ensure:

- source text is treated as data in prompts;
- prompt injection boundaries exist;
- file paths are sanitized;
- output paths cannot escape project storage;
- uploaded filenames are never blindly trusted;
- external responses are validated;
- API keys never enter logs.

## 12.4 Performance Review

Avoid:

- repeated LLM calls;
- unnecessary re-localization;
- duplicate TTS generation;
- duplicate HeyGen jobs;
- loading heavy models repeatedly;
- recomputing completed assets.

---

# 13. STEP 14 — DOCUMENTATION & DEVELOPER HANDOFF

## Objective

Make the repository understandable without conversation history.

Update:

- `README.md`
- `ARCHITECTURE.md`
- `.env.example`
- setup documentation
- development guide
- testing guide
- provider guide
- troubleshooting guide

## 13.1 README Must Explain

- what the system does;
- architecture overview;
- setup;
- Python version;
- FFmpeg requirement;
- environment variables;
- running FastAPI;
- running Streamlit;
- running tests;
- mock mode;
- optional live HeyGen mode.

## 13.2 Architecture Documentation

Include final diagram:

```text
Input
  ↓
LLM Script Workflow
  ↓
Localization
  ↓
TTS
  ↓
Avatar + Supporting Visuals
  ↓
Subtitles
  ↓
FFmpeg Composition
  ↓
Final Multilingual Training Videos
```

---

# 14. STEP 15 — FINAL ACCEPTANCE TEST

Before declaring completion:

Run the complete automated test suite.

Then execute an end-to-end mock project such as:

```text
Topic:
Workplace Phishing Defense

Audience:
Corporate Employees

Base:
en-US

Targets:
ar-SA
bn-BD

Duration:
60 seconds
```

Expected artifact tree should conceptually include:

```text
storage/projects/<project_id>/
  project.json

  scripts/
    source.json
    ar-SA.json
    bn-BD.json

  audio/
    ar-SA/
    bn-BD/

  avatars/
    ar-SA/
    bn-BD/

  subtitles/
    ar-SA/
    bn-BD/

  visuals/
    ar-SA/
    bn-BD/

  rendered/
    ar-SA/
    bn-BD/

  final/
    training_ar-SA.mp4
    training_bn-BD.mp4
```

If using mock avatar output, clearly label it as mock development output.

---

# 15. AUTONOMOUS SELF-REVIEW CHECKLIST

Before marking **every step** complete, review:

## Architecture

- Did I preserve provider abstraction?
- Did I introduce vendor coupling?
- Did I duplicate an existing service?
- Did I create another source of truth?

## Correctness

- Are IDs preserved?
- Are durations derived correctly?
- Are totals derived from children?
- Are paths deterministic?
- Are failures represented explicitly?

## Cost

- Did any automated test consume paid credits?
- Can tests run without external credentials?
- Is live API behavior guarded?

## Security

- Did I leak a secret?
- Is user/source text treated as data?
- Are file paths safe?
- Are remote responses validated?

## Testing

- Did targeted tests pass?
- Did the full suite pass?
- Did I add failure-path tests?
- Did I test regression behavior?

## Documentation

- Did I update `ARCHITECTURE.md`?
- Did I update `.env.example` for new config?
- Did I record current status?

If any answer is unsatisfactory, fix it before moving on.

---

# 16. AUTONOMOUS_PROGRESS.md

Create and continuously update:

```text
AUTONOMOUS_PROGRESS.md
```

After each step record:

```markdown
## Step N — Name

Status: COMPLETED / BLOCKED / PARTIAL

### Implemented
...

### Files Created
...

### Files Modified
...

### Tests
- targeted:
- full suite:
- result:

### API Usage
- paid calls:
- free external calls:
- mock calls:

### Self-Review Findings
...

### Fixes Applied
...

### Known Limitations
...

### Next Step
...
```

This file is the primary progress log for the user when they return.

Do not require the user to reconstruct progress from chat messages.

---

# 17. BLOCKER POLICY

Do not stop for normal implementation problems.

Solve:

- code bugs;
- test failures;
- refactoring;
- mock setup;
- local fallbacks;
- missing optional dependencies.

Only mark a feature as externally blocked when it genuinely requires something unavailable, for example:

- HeyGen API credentials;
- live paid credits;
- account-level external configuration.

Even then:

1. finish the provider architecture;
2. finish mocks;
3. finish unit tests;
4. finish integration interfaces;
5. document the blocker;
6. continue with all independent later steps.

Example:

```text
HeyGen live smoke test: BLOCKED — no live credential.
HeyGen provider implementation: COMPLETED.
Mock avatar integration: COMPLETED.
Pipeline development: CONTINUES.
```

---

# 18. NO SILENT SCOPE EXPANSION

Do not add large technologies without justification.

Avoid introducing:

- Celery;
- Redis;
- PostgreSQL;
- Kubernetes;
- cloud storage;
- paid media APIs;
- unnecessary agent frameworks;

unless an existing requirement genuinely needs them.

The MVP should remain understandable and runnable locally.

---

# 19. DEPENDENCY POLICY

Before adding a dependency ask:

1. Is this already solved by Python standard library?
2. Is there already an installed dependency that handles it?
3. Is the package compatible with Python 3.13?
4. Is it actively maintained?
5. Is it necessary?

Record exact installed versions.

Do not perform broad dependency upgrades unless required.

---

# 20. FINAL DEFINITION OF DONE

The project is considered technically complete when:

- Steps 1–15 are implemented or explicitly documented as optional/live-only;
- full automated test suite passes;
- one complete mock end-to-end project succeeds;
- source + localized scripts are aligned;
- TTS assets have real measured durations;
- subtitle assets are generated;
- local visual assets are generated;
- scene videos compose successfully;
- final multilingual MP4 outputs are produced in mock/dev mode;
- HeyGen provider is implemented behind abstraction;
- real HeyGen usage is optional and guarded;
- Streamlit can launch the workflow;
- FastAPI exposes the project workflow;
- documentation is complete;
- no API secrets are exposed;
- paid APIs are not consumed automatically.

---

# 21. FINAL EXECUTION INSTRUCTION

Begin from the current repository state.

First:

```text
VERIFY STEPS 1–4
RUN COMPLETE TEST SUITE
CREATE AUTONOMOUS_PROGRESS.md
```

Then continue automatically:

```text
STEP 5  → TTS
STEP 6  → HeyGen Avatar
STEP 7  → Subtitles
STEP 8  → Supporting Visuals
STEP 9  → FFmpeg Composition
STEP 10 → Full Pipeline Orchestration
STEP 11 → FastAPI Integration
STEP 12 → Streamlit UI
STEP 13 → Hardening
STEP 14 → Documentation
STEP 15 → Final Acceptance Test
```

At every stage:

```text
IMPLEMENT
→ TEST
→ SELF-REVIEW
→ FIX
→ FULL TEST SUITE
→ DOCUMENT
→ CONTINUE
```

Do not wait for human approval unless a truly unavoidable external blocker requires the user's action.

If a paid/live provider is unavailable, complete its mock/provider architecture and continue building the rest of the system.

The final repository must be runnable, testable, documented, and understandable without access to the original chat history.
