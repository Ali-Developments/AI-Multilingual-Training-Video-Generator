# Frontend Architecture — AI Training Video Studio V2

## Overview

The primary interface for the AI Multilingual Training Video Generator has transitioned from a single-page Streamlit prototype into a full-fledged, professional Next.js 14 App Router web application located in `web/`.

Streamlit is preserved strictly for legacy / internal debugging purposes at `frontend/streamlit_app.py`.

---

## 1. Technology Stack

- **Framework:** Next.js 14 (App Router)
- **Language:** TypeScript 5.0 (Strict mode enabled)
- **Styling:** Vanilla CSS + Tailwind CSS (Curated dark studio design system)
- **Icons:** Lucide React
- **Reverse Proxy:** Next.js rewrites forwarding `/api/v1/:path*` and `/storage/:path*` directly to FastAPI (`http://127.0.0.1:8000`)

---

## 2. Information Architecture & Navigation

The application consists of 6 primary routes designed desktop-first for multimedia production:

```
/
├── create/               # 5-Step Project Wizard
├── projects/             # Searchable Project Catalog & Management
├── media/                # Asset Library (Videos, B-Roll, Images)
├── settings/             # Hardware Diagnostics (CUDA, SadTalker, TTS, Groq)
└── studio/[id]/          # Interactive Scene Studio & Timeline
    └── export/           # Final Delivery & Multi-Asset Download Dashboard
```

---

## 3. Core Pages & Capabilities

### 3.1 Dashboard (`/`)
- **Metric Cards:** Real-time counters for Total Projects, Rendered Videos, and Active Languages.
- **Provider Readiness Pill:** Live polling of NVIDIA CUDA and SadTalker local environment status in the top navigation.
- **Recent Project Cards:** Rich project cards showing topic title, duration, source/target flags, thumbnail preview, provider badge, and status pill (Completed / In Progress / Failed).
- **Project Actions:** One-click Open Studio, Duplicate Project, and Delete.

### 3.2 Create Video Wizard (`/create`)
A structured 5-step workflow designed around enterprise training workflows:
1. **Content:** Project Title, Training Topic, Source Material, Target Audience, Desired Duration (slider 15s–180s).
2. **Languages:** Source Language (en-US, ar-SA, etc.) + Multi-target language selection matrix with RTL indicators.
3. **Video Style:** Selection between:
   - *Hybrid Presenter + B-Roll* (Default balanced training experience)
   - *Presenter-Led* (Instructor prominent throughout)
   - *Visual Explainer* (Dynamic motion visuals and keyphrase cards)
   - *Demonstration / Tutorial* (Culinary, laboratory, and procedural training)
   - *Corporate Training* (Compliance, policy, and quiz checks)
4. **Presenter Studio:** Selection of Avatar Provider (`SadTalker Local (Free / CUDA)`, `HeyGen (Cloud Premium)`, or `Mock Engine`) and instructor portrait.
5. **Review & Generate:** Choice between **Studio Mode** (open editor to customize scenes before rendering) and **Quick Generate** (one-click end-to-end automation).

### 3.3 Scene Editor & Timeline Studio (`/studio/[id]`)
A three-column desktop editing environment inspired by professional NLE tools:
- **Left Column (Scene List):**
  - Scene cards displaying scene number, media type badge, duration, and avatar indicator.
  - Reorder controls (Move Up / Move Down) that sync order indices to the backend.
  - Add Scene button for dynamic storyboarding.
- **Center Column (16:9 Video Canvas):**
  - HTML5 video player supporting scene-level preview and full final video playback.
  - Interactive lower-third subtitle safe zone displaying Arabic RTL / English typography.
  - Transport bar with Play/Pause, Seek bar, and Duration readouts.
- **Right Column (Scene Inspector):**
  - Scene Media Type selector (`presenter`, `broll`, `uploaded_video`, `uploaded_image`, `motion_visual`, `diagram`, `title`, `quiz`, `outro`).
  - Layout Type selector (`presenter_split`, `presenter_full`, `media_full`, `media_with_overlay`, `quiz_card`, `title_card`).
  - Narration text editor with automatic downstream cache invalidation.
  - Presenter Toggle (Enable/Disable avatar for this specific scene).
  - Media prompt and search term tags.
  - Quiz editor fields (Question, Options A/B/C/D, Correct Choice).
  - Per-scene action buttons: *Regenerate Audio*, *Regenerate Avatar*, *Regenerate Visual*, *Render Scene*.
- **Bottom Timeline Strip:**
  - Visual blocks scaled to scene duration.
  - Live total project duration calculation with target tolerance comparison.

### 3.4 Delivery & Export Dashboard (`/studio/[id]/export`)
- Full 16:9 MP4 preview player.
- Locale selector allowing instant switching between generated language tracks (`ar-SA`, `en-US`, etc.).
- Technical specifications table: Resolution (1920×1080), Duration, Video Codec (H.264), Audio Codec (AAC 48,000 Hz Stereo), Subtitle format (ASS/SRT).
- Single-click download buttons for:
  - Final Master Video (`.mp4`)
  - Normalized 48kHz Audio Track (`.wav`)
  - Localized Subtitles (`.srt`)

---

## 4. Design System & Aesthetics

- **Dark Slate Backgrounds:** Base `#090D1A`, panels `#0F172A` with fine borders (`border-slate-800`).
- **Accent Colors:** Electric Cyan (`#06B6D4`) for primary interactive elements, Emerald (`#10B981`) for completed statuses, Amber (`#F59E0B`) for premium/warning badges.
- **Typography:** Modern sans-serif with RTL bidirectional isolation for Arabic text blocks.
- **Zero Template Artifacts:** The UI suppresses all internal developer logs and variable names from user-facing presentations.
