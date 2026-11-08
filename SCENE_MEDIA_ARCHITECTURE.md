# Scene Media Architecture — AI Training Video Studio V2

## Overview

Video Studio V2 replaces the legacy PowerPoint slide + corner avatar approach with an **instructor-led cinematic video composition engine**. The visual architecture ensures the presenter genuinely leads the training experience, supported by full-screen B-roll, dynamic motion visuals, contextual overlays, and knowledge-check quiz scenes.

---

## 1. Scene Media Types (`SceneMediaType`)

| Scene Media Type | Description | Audio / Avatar Behavior |
| :--- | :--- | :--- |
| `presenter` | Primary instructor scene | SadTalker talking-head avatar enabled |
| `broll` | Contextual video or dynamic motion B-roll | Avatar disabled; narration + subtitles + motion |
| `uploaded_video` | User-supplied video asset (.mp4, .webm, .mov) | Full-screen or split; synced to narration duration |
| `uploaded_image` | User-supplied still graphic (.png, .jpg, .webp) | Animated via Ken Burns motion zoom |
| `motion_visual` | Algorithmic pan/zoom video generated from prompt/theme | Avatar disabled; cinematic camera motion |
| `diagram` | Informational architectural or flow diagram | Minimalist slate layout with clear labels |
| `title` | Opening title board or chapter divider | Clean typography, project branding, and accent |
| `quiz` | Formative evaluation question with choices | Option cards with clear visual hierarchy |
| `outro` | Concluding takeaways and call-to-action | Presenter full or split with closing CTA |

---

## 2. Layout Types (`SceneLayoutType`)

| Layout Type | Aspect / Geometry | Primary Use Case |
| :--- | :--- | :--- |
| `presenter_split` | 42% Presenter (Left) / 58% Media (Right) | Core educational explanations, tutorials |
| `presenter_full` | Centered 960×960 framed avatar on studio canvas | Intro hook, important warnings, outro |
| `media_full` | 1920×1080 full-bleed visual or motion video | Physical demonstrations, B-roll footage |
| `media_with_overlay` | 1920×1080 media with lightweight keyphrase card | Focus takeaways, glossary terms |
| `presenter_overlay` | Full-bleed media with framed presenter PIP | High-context software/screen walkthroughs |
| `title_card` | Studio canvas with centered title and branding | Module headers, chapter introductions |
| `quiz_card` | Studio canvas with question and option pills | Knowledge check scenes |

---

## 3. Presenter-Led Visual Composition System

### 3.1 The `presenter_split` Standard
In the legacy prototype, avatars were scaled down to tiny corner boxes over dense PowerPoint cards. In V2:
- **Left Column (42% Width, ~806px):** Dedicated presenter space. The SadTalker avatar (rendered at native high resolution) is scaled to 806×806 and padded to 1080h on a dark studio slate backdrop (`#0B0F19`).
- **Divider Line:** A subtle cyan accent line (`#06B6D4`, 2px) separates the presenter from the supporting media.
- **Right Column (58% Width, ~1114px):** Displays full-height contextual media, B-roll video, or motion visuals.
- **Lower Third:** Standardized subtitle safe zone reserved for ASS / libass Arabic and English subtitles.

```
+-----------------------------------------------------------------------+
|  1920x1080 Canvas                                                     |
|  +-------------------------+---+------------------------------------+ |
|  |                         |   |                                    | |
|  |   SadTalker Avatar      |   |   Contextual Media / B-Roll        | |
|  |   806 x 806 centered    | | |   1114 x 1080                      | |
|  |   on Dark Studio Slate  |   |   (Motion Visual / Video / Image)  | |
|  |                         |   |                                    | |
|  +-------------------------+---+------------------------------------+ |
|  |      Lower-Third Subtitle Safe Zone (libass / Arabic RTL)         | |
+-----------------------------------------------------------------------+
```

### 3.2 The `presenter_full` Standard
SadTalker native resolutions should not be stretched to 1920×1080 directly to avoid pixelation. Instead, V2 places the avatar in a centered 960×960 framed container with subtle edge vignette and dark studio gradient backdrop, maintaining crisp facial detail while reserving clear typography space.

---

## 4. Local Motion Visual Provider (`LocalMotionVisualProvider`)

Static Pillow slides have been replaced by the **Local Motion Visual Engine**, utilizing FFmpeg's `zoompan` filter to transform still concepts into cinematic B-roll:

```bash
ffmpeg -loop 1 -i scene_visual.png \
  -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=150:s=1920x1080:fps=30" \
  -c:v libx264 -pix_fmt yuv420p -t {duration} motion_scene.mp4
```

- **Smooth Zoom:** Slow 0.08% frame-by-frame zoom gives static visuals continuous life.
- **Completely Free & Local:** Executes on CPU or NVIDIA GPU via standard FFmpeg without external paid API calls.

---

## 5. Media Provider Architecture

The orchestration engine decouples media sources via `SceneMediaService`:
1. `UploadedMediaProvider`: Ingests user-provided MP4, WebM, PNG, JPG assets stored in `storage/projects/{id}/media/`.
2. `LocalMotionVisualProvider`: Synthesizes motion clips using the Ken Burns filter.
3. `LocalVisualProvider`: Generates lightweight branding and quiz cards using Pillow.
4. `OptionalGeneratedVideoProvider`: Extensible placeholder for future generative models (Google Veo, etc.) kept disabled by default.

---

## 6. Visual Quality Rules & Metadata Elimination

To ensure client-ready production value:
- **Zero Developer Metadata:** Internal keys such as `"SCENE 4"`, `"OUTRO"`, `"SUMMARY CARD"`, `"OBJECTIVE"`, `"Content delivery"`, and `"scene_4"` are strictly purged from video templates.
- **Arabic Typography:** Native RTL font rendering with libass / HarfBuzz shaping.
- **Normalized Audio:** 48,000 Hz, stereo AAC, -16 LUFS broadcast target.
