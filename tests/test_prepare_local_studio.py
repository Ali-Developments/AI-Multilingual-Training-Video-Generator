import wave

import pytest

from app.workflows.manifest import ProjectManifestManager
from scripts.prepare_local_studio import prepare


def test_local_audio_import_is_renderable_without_replacing_existing_project(tmp_path):
    source = tmp_path / "intro.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes(2 * 16000 * 16))
    lesson = {"title": "Orientation", "locale": "en-US", "scenes": [
        {"title": "Welcome", "narration": "Welcome to orientation.", "wav": source.name}
    ]}
    storage = tmp_path / "projects"
    prepare(lesson, tmp_path, "orientation", storage)
    manifest = ProjectManifestManager(storage).load_manifest("orientation")
    assert manifest.source_request.avatar_provider == "sadtalker"
    assert manifest.script_status == manifest.localization_status == manifest.audio_status == "completed"
    assert manifest.audio_tracks["en-US"].total_audio_duration_seconds == 16
    assert manifest.avatar_status == manifest.composition_status == "pending"
    assert not manifest.final_videos and not manifest.avatar_tracks
    assert (storage / "orientation/audio/en-US/scene_1.wav").read_bytes() == source.read_bytes()
    original = (storage / "orientation/project.json").read_bytes()
    with pytest.raises(FileExistsError):
        prepare(lesson, tmp_path, "orientation", storage)
    assert (storage / "orientation/project.json").read_bytes() == original
