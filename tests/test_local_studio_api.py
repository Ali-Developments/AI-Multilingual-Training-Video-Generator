import io
import wave

from fastapi.testclient import TestClient

from app.workflows.manifest import ProjectManifestManager
from scripts.local_studio_api import ROUTE, app, settings


def pcm_wav(seconds):
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(2 * 16000 * seconds))
    return data.getvalue()


def test_local_form_opens_fresh_recorded_project(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PATH", tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get(ROUTE).status_code == 200
    data = {"title": "Orientation", "locale": "en-US", "narration": "Welcome to orientation."}
    result = client.post(ROUTE, data=data, files={"wav": ("speaker.wav", pcm_wav(16))}, follow_redirects=False)
    assert result.status_code == 303
    location = result.headers["location"]
    assert location.startswith("/studio/local_")
    manifest = ProjectManifestManager(tmp_path).load_manifest(location.split("/")[-1])
    assert manifest.audio_tracks["en-US"].total_audio_duration_seconds == 16
    assert manifest.avatar_status == "pending"


def test_recorded_lesson_returns_helpful_errors_before_creating_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PATH", tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1")
    data = {"title": "Orientation", "locale": "en-US", "narration": "Check your badge."}
    for audio, locale, message in [
        (b"fake", "en-US", "PCM WAV"),
        (pcm_wav(1), "en-US", "15–3600 seconds"),
        (pcm_wav(16), "invalid_locale", "locale identifier"),
    ]:
        result = client.post(ROUTE, data={**data, "locale": locale}, files={"wav": ("speaker.wav", audio)})
        assert result.status_code == 422
        assert message in result.text
    assert not list(tmp_path.iterdir())
