# Local Engineering Health Audit

**Date**: 2026-11-19  
**Scope**: Full local codebase audit (backend, frontend, AI/LLM integration, staged script generation, checkpoint/resume, FFmpeg composition, storyboard planning, and offline test suites).  
**Execution Mode**: Strictly local & offline (zero live API calls, zero GitHub writes).

---

## 1. Executive Summary & Baseline Status

- **Targeted Script / Checkpoint / OpenRouter / Decompression / Cancellation Suite**: **181 passed, 0 failed, 1 deselected** (when run standalone).
- **Full Backend Offline Suite (`tests/ -k "not phase_a_smoke_test_30s_pipeline"`)**: **468 passed, 12 failed, 1 deselected**.
- **Frontend (`web/`)**: **33/33 tests passed**, `next build` succeeded, `next lint` passed with **1 warning** (`no-unused-vars`).
- **Root-Cause Classification of All Observed Issues**:
  - **2 Confirmed Production Bugs** (storyboard overwrite during `run_project`, `demonstration_tutorial` ignoring `scene_type="demonstration"`).
  - **1 Confirmed Lint / Code-Hygiene Warning** (unused `isPresenter` in Studio scene list).
  - **10 Test-Only Failures** (9 FFmpeg mock tests missing `validate_video_file` stub after production validation hardening; 1 timing-sensitive timeout test with an overly tight `0.15s` budget).
  - **2 Previously Confirmed Production Bugs Verified Fixed** (OpenRouter double decompression in `openrouter_provider.py`, and `proj_5349ccdf48f0` 260s timeout misclassified as `"Script run was cancelled"`).

---

## 2. Detailed Problem Inventory

### PROB-01 — Custom Approved Storyboard Overwritten During `run_project()`
- **Classification**: Confirmed Production Bug
- **Severity**: **High**
- **Affected Component**: `ProjectOrchestrator.run_project()`
- **Exact Location**: [`app/workflows/orchestrator.py:473-482`](file:///d:/Freelancing-Projects/Video-Automation/AI-Multilingual-Training-Video-Generator/app/workflows/orchestrator.py#L473-L482)
- **Observed Behavior**: `has_existing_storyboard` requires `getattr(s, "preferred_provider", None) is not None` for every scene. When a user edits/approves a storyboard in Studio (where `layout_type`, `media_type`, and `visual_prompt` are set, but `preferred_provider` is `None`), `run_project()` evaluates `has_existing_storyboard = False` and calls `StoryboardPlanner.plan_storyboard()`, overwriting custom scene edits.
- **Expected Behavior**: Existing approved storyboards with populated `layout_type`, `media_type`, and either `visual_prompt` or `preferred_provider` must be preserved unless `force_regenerate=True`.
- **Reproduction**: `pytest tests/test_v2_render_and_preview.py -k test_storyboard_is_reused_during_run_project` → `AssertionError: Expected 'plan_storyboard' to not have been called. Called 1 times.`
- **Proposed Fix**: Update `has_existing_storyboard` check to accept `(getattr(s, "preferred_provider", None) is not None or bool(getattr(s, "visual_prompt", None)))`.
- **Regression Test**: `tests/test_v2_render_and_preview.py::test_storyboard_is_reused_during_run_project`.

---

### PROB-02 — `DEMONSTRATION_TUTORIAL` Style Ignores Explicit `scene_type="demonstration"`
- **Classification**: Confirmed Production Bug
- **Severity**: **Medium**
- **Affected Component**: `StoryboardPlanner.plan_storyboard()`
- **Exact Location**: [`app/workflows/storyboard_planner.py:176-198`](file:///d:/Freelancing-Projects/Video-Automation/AI-Multilingual-Training-Video-Generator/app/workflows/storyboard_planner.py#L176-L198)
- **Observed Behavior**: Unlike the `HYBRID_PRESENTER_BROLL` branch (line 207), the `DEMONSTRATION_TUTORIAL` branch only checks `demo_keywords` in `text_lower`/`topic_clean` and omits `stype in ("visual_demo", "demonstration", "example")`. Consequently, body scenes explicitly typed `scene_type="demonstration"` (e.g., Saudi Kabsa cooking scenes) are downgraded to `media_type="presenter"` instead of `broll`.
- **Expected Behavior**: Body scenes with `scene_type in ("visual_demo", "demonstration", "example")` under `demonstration_tutorial` must be planned as `SceneMediaType.BROLL`.
- **Reproduction**: `pytest tests/test_studio_bootstrap.py -k test_kabsa_demonstration_storyboard_scenes_avoid_generic_cards` → `AssertionError: assert 'presenter' == 'broll'`.
- **Proposed Fix**: Include `stype in ("visual_demo", "demonstration", "example")` in the `DEMONSTRATION_TUTORIAL` condition (matching line 207).
- **Regression Test**: `tests/test_studio_bootstrap.py::test_kabsa_demonstration_storyboard_scenes_avoid_generic_cards`.

---

### PROB-03 — Flaky `0.15s` Timeout Budget in Cancellation/Timeout Regression Test
- **Classification**: Test-Only Failure (Timing Sensitivity)
- **Severity**: **Medium**
- **Affected Component**: `tests/test_run_cancellation_and_timeout.py`
- **Exact Location**: [`tests/test_run_cancellation_and_timeout.py:224`](file:///d:/Freelancing-Projects/Video-Automation/AI-Multilingual-Training-Video-Generator/tests/test_run_cancellation_and_timeout.py#L224)
- **Observed Behavior**: Under heavy CPU load during the full 480-test suite, `ScriptCheckpoint.compute_identity()` (hashing 8 source files) + `ContentAnalysis` exceeded `0.15s` before `ScriptOutline` began, causing the test to time out during `outline` instead of `scene_1`.
- **Expected Behavior**: Test should deterministically accept `analysis` and `outline`, then hit the run deadline during `scene_1`.
- **Proposed Fix**: Raise the test's `OPENROUTER_SCRIPT_TIMEOUT_SECONDS` to `1.2s` (with `scene_1` sleeping `1.5s` and `timeout_seconds=0.8s`), eliminating CPU-load sensitivity while still verifying real `RunControl` wall-clock timeout and resume.
- **Regression Test**: `tests/test_run_cancellation_and_timeout.py::test_timeout_reports_script_timeout_not_cancelled_and_resumes_cleanly`.

---

### PROB-04 — 9 Mocked FFmpeg Tests Fail `validate_video_file` After Production Validation Hardening
- **Classification**: Test-Only Failure
- **Severity**: **Medium**
- **Affected Component**: `tests/test_duration_reconciliation.py` (3 tests) and `tests/test_master_local_pipeline.py` (6 tests)
- **Exact Location**:
  - [`tests/test_duration_reconciliation.py:166-265`](file:///d:/Freelancing-Projects/Video-Automation/AI-Multilingual-Training-Video-Generator/tests/test_duration_reconciliation.py#L166-L265)
  - [`tests/test_master_local_pipeline.py:605-765`](file:///d:/Freelancing-Projects/Video-Automation/AI-Multilingual-Training-Video-Generator/tests/test_master_local_pipeline.py#L605-L765)
- **Observed Behavior**: These 9 tests mock `subprocess.run` to inspect FFmpeg CLI arguments (`-t`, `-shortest`, `-ar 48000`, `-ac 2`, RTL subtitles) without creating an actual MP4 file. Production `FFmpegCompositionProvider` rightly calls `validate_video_file(output_path, ...)` after `subprocess.run`, raising `FileNotFoundError`.
- **Expected Behavior**: Mocked FFmpeg CLI-flag tests should mock `validate_video_file` (or materialize a stub file + mock `ffprobe`) without weakening production `validate_video_file()` checks.
- **Proposed Fix**: Patch `app.services.composition.ffmpeg_provider.validate_video_file` in those 9 mocked-subprocess unit tests only, keeping production `validate_video_file()` untouched.

---

### PROB-05 — Unused Variable ESLint Warning in Scene Studio
- **Classification**: Code Hygiene / Lint Warning
- **Severity**: **Low**
- **Affected Component**: Next.js Scene Studio
- **Exact Location**: [`web/src/app/studio/[id]/page.tsx:438`](file:///d:/Freelancing-Projects/Video-Automation/AI-Multilingual-Training-Video-Generator/web/src/app/studio/%5Bid%5D/page.tsx#L438)
- **Observed Behavior**: `const isPresenter = sc.media_type === 'presenter' || sc.avatar_enabled;` is declared but never referenced, emitting an ESLint warning during `npm run lint` and `npm run build`.
- **Proposed Fix**: Remove the unused declaration.

---

### PROB-06 — Verified Previously-Fixed Critical Issues (Audit Confirmation)
- **Multilingual Source Handling** (`app/core/language.py`, `app/models/schemas.py`, `nodes.py`): Confirmed fixed — source, canonical, and target languages are decoupled; non-blocking `language_warnings` replace HTTP 422 blocking (`12/12` passing in `test_multilingual_source_handling.py`).
- **OpenRouter Double Decompression** (`app/services/llm/openrouter_provider.py`): Confirmed fixed — `content-encoding`/`content-length`/`transfer-encoding` stripped from synthetic `httpx.Response` built from `incoming.iter_bytes()`, plus dedicated `OpenRouterDecodingError` (`10/10` passing in `test_openrouter_decompression.py`).
- **`proj_5349ccdf48f0` Timeout Misclassified as Cancellation** (`storage.py`, `openrouter_provider.py`, `checkpoint.py`, `orchestrator.py`): Confirmed fixed — per-run `RunControl(run_id, timeout_seconds)` separates `OpenRouterTimeoutError` (`SCRIPT_TIMEOUT`) from `OpenRouterCancelledError` (`SCRIPT_CANCELLED`) and allows `checkpoint.finish(False, reason=...)` to close interrupted runs cleanly.
- **Checkpoint/Resume, OS Locking, Durable `RequestLedger`, Paid-Model Gate**: Confirmed implemented and verified (`181/181` passing in targeted reliability suites).

---

### PROB-07 — External & Deployment Limitations (Informational)
- **OpenRouter Free-Router Latency**: Upstream free endpoints routed by `openrouter/free` can take 25–90s per call; 6-scene live runs may still span multiple 260s windows using checkpoint resume.
- **Single-Machine Local Locking**: `msvcrt.locking` / `fcntl.flock` protects concurrent processes on one host sharing local storage, not multi-node or network-share deployments.

