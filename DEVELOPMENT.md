# Developer Guide & Execution Protocol

## 1. Development Principles
- **Clean Architecture**: Services depend strictly on abstract base classes (`LLMProvider`, `TTSProvider`, `AvatarProvider`, `SubtitleProvider`, `VisualAssetProvider`, `CompositionProvider`).
- **Timing Ground Truth**: Audio waveform duration measured from generated speech files is the single ground truth for scene timing across the pipeline.
- **Cost Safety Policy**: All test runs and local continuous integrations enforce `ENABLE_LIVE_API_TESTS=False`. Paid external credits are never consumed automatically.
- **Cross-Platform Compatibility**: All file paths use `pathlib.Path` with safe Windows path and filter escaping.

---

## 2. Environment Setup & Execution

### Python Virtual Environment
Use the dedicated virtual environment in `.venv/`:
```bash
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Linux / macOS
.venv/bin/python -m pip install -r requirements.txt
```

### Running Test Suite
Run the complete regression suite:
```bash
.venv\Scripts\python.exe -m pytest -v
```

Run targeted tests for specific modules:
```bash
.venv\Scripts\python.exe -m pytest tests/test_orchestrator.py -v
.venv\Scripts\python.exe -m pytest tests/test_api_projects.py -v
.venv\Scripts\python.exe -m pytest tests/test_frontend.py -v
.venv\Scripts\python.exe -m pytest tests/test_hardening_failures.py -v
```

### Launching the Backend API
```bash
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Launching the Streamlit Studio Frontend
```bash
.venv\Scripts\python.exe -m streamlit run frontend/streamlit_app.py
```

---

## 3. Adding New Service Providers

To introduce a new provider (e.g., ElevenLabs for TTS, Anthropic for LLM, or D-ID for Avatars):
1. Add configuration parameters to `app/core/config.py` and `.env.example`.
2. Implement the interface in `app/services/<service_type>/`:
   - Subclass the base interface (e.g. `TTSProvider` in `app/services/tts/base.py`).
   - Implement all abstract methods.
3. Register the new provider key in the corresponding factory:
   - e.g., `app/services/tts/factory.py`.
4. Add isolated unit tests using mocks in `tests/test_<service_type>.py`.

---

## 4. Troubleshooting & Gotchas

- **FFmpeg Subtitle Filter Escaping on Windows**:
  FFmpeg's `subtitles` filter treats colons (`:`) and backslashes (`\`) as special delimiter characters. Use `escape_ffmpeg_filter_path()` from `app.services.composition.ffmpeg_utils` to ensure Windows drive letters (`C\:...`) do not break subtitle rendering.
- **Unicode Support (Arabic & Bengali)**:
  `LocalVisualProvider` utilizes Unicode fonts with fallback support to ensure Arabic RTL glyphs and Bengali complex ligatures render cleanly on Full HD slide cards without box replacement characters.
- **Circular Imports**:
  Never import `ProjectOrchestrator` directly inside `app/workflows/__init__.py` at module initialization time, as downstream validators in `app/services/localization` depend on `estimate_narration_duration_seconds` from `app.workflows.script_generation`.
