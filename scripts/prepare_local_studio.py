"""Import local WAV narration and its transcript into a fresh renderable Studio project.

Run from the repo root with python -m scripts.prepare_local_studio. By default the
two Arabic scenes from the Phase 10 demonstration supply the narration. To import
your own recordings, use --lesson lesson.json, for example:

    {"title": "New hire welcome", "locale": "en-US", "scenes": [
        {"title": "Welcome", "wav": "intro.wav", "narration": "Exact spoken transcript..."}
    ]}

Relative WAV paths are resolved beside the lesson JSON. The API and this script
must use the same STORAGE_PATH. The GPU render is started separately from Studio.
"""
import argparse
import json
import re
import shutil
import wave
from pathlib import Path
from uuid import uuid4

from app.core.config import settings
from app.models.schemas import (
    FinalScript, LocalizationBundle, LocalizedAudioTrack, LocalizedScene, LocalizedScript,
    ProjectManifest, SceneAudioAsset, SceneDraft, TrainingVideoRequest,
)
from app.services.localization.locale_utils import get_text_direction, normalize_locale
from app.workflows.manifest import ProjectManifestManager


def demo_lesson():
    audio = Path(__file__).resolve().parents[1] / "storage/demonstrations/phase10_persistent/audio/ar-SA"
    return {
        "title": "التحقق من رسائل التصيد والإبلاغ عنها", "locale": "ar-SA", "voice": "ar-SA-HamedNeural",
        "scenes": [
            {"title": "التحقق من نطاق المرسل", "wav": audio / "scene_2.wav",
             "narration": "احرص دائماً على تمرير المؤشر فوق اسم المرسل للتحقق من النطاق الحقيقي قبل الضغط على أي روابط.",
             "visual": "Inspect the email sender domain."},
            {"title": "بروتوكول الإبلاغ المؤسسي", "wav": audio / "scene_3.wav",
             "narration": "عند رصد أي رسالة مشبوهة، لا تقم بإعادة توجيهها بل اضغط زر الإبلاغ لعزل التهديد وإخطار فريق الأمن فوراً.",
             "visual": "Report the suspicious message to the incident response team."},
        ],
    }


def prepare(lesson, base_dir, project_id, storage):
    locale = normalize_locale(lesson["locale"])
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", project_id):
        raise ValueError("Use only letters, numbers, underscores or hyphens in project ID")
    project_dir = Path(storage).resolve() / project_id
    drafts, local_scenes, assets, inputs = [], [], [], []
    for order, entry in enumerate(lesson["scenes"], 1):
        transcript = entry["narration"].strip()
        if not transcript:
            raise ValueError(f"Scene {order} has no transcript")
        source = (base_dir / entry["wav"]).resolve(strict=True)
        try:
            with wave.open(str(source), "rb") as wav:
                if wav.getframerate() <= 0 or wav.getcomptype() != "NONE":
                    raise ValueError("Use an uncompressed PCM WAV recording.")
                duration = wav.getnframes() / wav.getframerate()
                frame_bytes = wav.getnchannels() * wav.getsampwidth()
                payload_bytes = sum(len(data) for data in iter(lambda: wav.readframes(65536), b""))
                if payload_bytes != wav.getnframes() * frame_bytes:
                    raise ValueError("The WAV recording is incomplete. Export it again.")
        except (EOFError, wave.Error) as exc:
            raise ValueError("Use an uncompressed PCM WAV recording.") from exc
        if duration <= 0:
            raise ValueError(f"Empty narration file: {source}")
        scene_id = f"scene_{order}"
        draft = SceneDraft(
            scene_id=scene_id, order=order, title=entry["title"], narration=transcript,
            estimated_duration_seconds=max(1, round(duration)), media_type="motion_visual",
            visual_direction=entry.get("visual", entry["title"]), preferred_provider="local_motion",
            layout_type="presenter_picture_in_picture", presenter_position="right", avatar_enabled=True,
        )
        drafts.append(draft)
        local_scenes.append(LocalizedScene.model_validate(draft.model_dump()))
        destination = project_dir / "audio" / locale / f"{scene_id}.wav"
        inputs.append((source, destination))
        assets.append(SceneAudioAsset(
            scene_id=scene_id, locale=locale, duration_seconds=duration, audio_path=str(destination),
            provider="local_recording", voice_id=lesson.get("voice", "recorded"),
        ))
    total = sum(asset.duration_seconds for asset in assets)
    if not 15 <= total <= 3600:
        raise ValueError(f"Studio supports 15–3600 seconds of narration (received {total:.2f}s)")
    request = TrainingVideoRequest(
        topic=lesson["title"], source_content=" ".join(s.narration for s in drafts),
        base_language=locale, target_languages=[locale], target_duration_seconds=round(total),
        avatar_provider="sadtalker", persistent_presenter=True, video_style="presenter_led",
    )
    common = dict(title=lesson["title"], language=locale, audience=request.audience,
                  target_duration_seconds=round(total), total_estimated_duration_seconds=round(total),
                  opening_hook=drafts[0].title, closing_summary=drafts[-1].title)
    script = FinalScript(**common, scenes=drafts)
    localized = LocalizedScript(**common, source_language=locale, locale=locale,
                                text_direction=get_text_direction(locale), scenes=local_scenes)
    manifest = ProjectManifest(
        project_id=project_id, source_request=request, avatar_provider="sadtalker",
        final_script=script, script_status="completed", localization_status="completed",
        localization_bundle=LocalizationBundle(source_script=script, localized_scripts={locale: localized}),
        audio_status="completed", audio_tracks={locale: LocalizedAudioTrack(
            locale=locale, scene_audio=assets, total_audio_duration_seconds=total,
        )},
        metadata={"input_source": "imported local narration and transcript"},
    )
    project_dir.mkdir(parents=True, exist_ok=False)
    for source, destination in inputs:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    ProjectManifestManager(storage_base_dir=project_dir.parent).save_manifest(manifest)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", default=f"local_e2e_{uuid4().hex[:12]}")
    parser.add_argument("--lesson", type=Path)
    args = parser.parse_args()
    lesson = json.loads(args.lesson.read_text(encoding="utf-8-sig")) if args.lesson else demo_lesson()
    manifest = prepare(lesson, args.lesson.parent if args.lesson else Path.cwd(), args.project_id, settings.STORAGE_PATH)
    print(f"Studio project: /studio/{manifest.project_id}")
