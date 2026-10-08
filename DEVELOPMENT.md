# Developer Guide & Execution Protocol

## 1. Development Principles
- **Clean Architecture**: Services depend strictly on abstract base classes (`LLMProvider`, `TTSProvider`, `AvatarProvider`, `SubtitleProvider`, `VisualAssetProvider`, `CompositionProvider`).
- **Timing Ground Truth**: Audio waveform duration measured from generated speech files is the single ground truth for scene timing across the pipeline.
- **Dedicated Post-TTS Duration Reconciliation**: When spoken audio drifts beyond configured tolerances, `DurationReconciliationService` deterministically condenses narration without losing pedagogical content.
- **Cost Safety Policy**: All automated test runs enforce `ENABLE_LIVE_API_TESTS=False`. Paid external avatar credits (HeyGen) are never consumed automatically.
- **SadTalker Environment Isolation**: The local talking avatar engine runs in an isolated Python 3.10 virtualenv (`.sadtalker-venv/`) to prevent polluting the main Python 3.13 production runtime.
- **Cross-Platform Compatibility**: All file paths use `pathlib.Path` with safe Windows path and filter escaping.

---

## 2. Environment Setup & Execution

### Main Application Environment (`.venv`)
```bash
# Windows
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Free Local SadTalker Avatar Setup (`.sadtalker-venv`)
To set up the free GPU-accelerated local talking-head avatar engine:
```powershell
# Run the automated SadTalker bootstrap script
powershell -ExecutionPolicy Bypass -File scripts\setup_sadtalker.ps1
```
This script automatically:
1. Clones the SadTalker repository into `tools/sadtalker/`.
2. Creates an isolated Python 3.10 virtual environment in `.sadtalker-venv/`.
3. Installs CUDA-enabled PyTorch (`torch 2.1+cu118`) and pinned dependencies (`numpy==1.23.5`).
4. Verifies model checkpoints (`SadTalker_V0.0.2_256.safetensors`, `mapping_00229-model.pth.tar`, `mapping_00109-model.pth.tar`) in `tools/sadtalker/checkpoints/`.
5. Confirms source presenter portrait in `assets/avatars/local_presenter.png`.

---

## 3. Running the Test Suite

Run the full regression test suite (255 tests):
```bash
.\.venv\Scripts\python.exe -m pytest -v
```

Run targeted test modules:
```bash
# Master Local Video Generation Pipeline tests (36 comprehensive tests)
.\.venv\Scripts\python.exe -m pytest tests/test_master_local_pipeline.py -v

# Post-TTS Duration Reconciliation tests
.\.venv\Scripts\python.exe -m pytest tests/test_duration_reconciliation.py -v

# Orchestrator & End-to-end orchestration tests
.\.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py -v
```

---

## 4. Running the Real Local E2E Acceptance Test

To execute a complete live local video generation run (Groq -> Localization -> Edge-TTS -> Duration Reconciliation -> SadTalker CUDA -> Local Visuals -> ASS Subtitles -> FFmpeg):
```bash
.\.venv\Scripts\python.exe scripts\run_master_acceptance.py
```
This generates `training_ar-SA.mp4` under `storage/projects/proj_local_video_generation_acceptance/final/` and saves an automated validation report to `acceptance_report.json`.

---

## 5. Launching Applications

### FastAPI REST Backend
```bash
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Streamlit Studio Frontend
```bash
.\.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py
```
The Streamlit interface allows selecting **SadTalker Local (Free)**, custom presenter portrait uploads, target durations, and provides a real-time Duration Reconciliation monitor with revision attempt metrics.
