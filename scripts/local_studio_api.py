"""Development entry point for Studio with local recorded narration. Bind to loopback."""
from html import escape
from pathlib import Path
from shutil import copyfileobj
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.core.config import settings
from app.main import create_app
from scripts.prepare_local_studio import prepare

app = create_app()
ROUTE = "/api/v1/local-lesson"
MAX_WAV_BYTES = 32 * 1024 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def lesson_form(message="", status=200):
    alert = f'<p role="alert">{escape(message)}</p>' if message else ""
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Create a local training video</title><style>
    *{{box-sizing:border-box}}body{{margin:2.5rem auto;padding:0 1rem;max-width:38rem;background:#0f172a;color:#f1f5f9;font:16px/1.5 system-ui}}
    label{{display:block;margin:1rem 0 .25rem;font-weight:600}}input,textarea{{width:100%;padding:.65rem;background:#182338;color:inherit;border:1px solid #64748b;border-radius:.35rem;font:inherit}}
    button{{margin-top:1rem;padding:.65rem 1rem;background:#67e8f9;color:#082f49;border:0;border-radius:.35rem;font:inherit;font-weight:650;cursor:pointer}}
    a{{color:#67e8f9}}[role=alert]{{color:#fecaca}}</style></head><body><main>
    <a href="/create">Back to Create</a><h1>Create a local training video</h1>
    <p>Use your recording as the presenter’s narration. Open the project in Studio to review the scene and render it.</p>{alert}
    <form method="post" enctype="multipart/form-data">
    <label for="title">Lesson title</label><input id="title" name="title" maxlength="160" required>
    <label for="locale">Recording language</label><input id="locale" name="locale" value="ar-SA" placeholder="ar-SA or en-US" maxlength="32" required>
    <label for="wav">PCM WAV recording (15 seconds to 1 hour, up to 32 MiB)</label><input id="wav" name="wav" type="file" accept=".wav,audio/wav" required>
    <label for="narration">Transcript in the recording language</label><textarea id="narration" name="narration" rows="5" maxlength="50000" required></textarea>
    <button type="submit">Open in Studio</button></form></main></body></html>""", status_code=status)


@app.get(ROUTE, response_class=HTMLResponse)
async def get_lesson_form():
    return lesson_form()


def import_recording(upload, title, locale, transcript):
    with TemporaryDirectory(prefix="studio-recording-") as directory:
        folder = Path(directory)
        with (folder / "recording.wav").open("wb") as wav:
            copyfileobj(upload.file, wav)
        lesson = {"title": title, "locale": locale, "scenes": [
            {"title": title, "wav": "recording.wav", "narration": transcript}
        ]}
        return prepare(lesson, folder, f"local_{uuid4().hex[:12]}", settings.STORAGE_PATH)


@app.post(ROUTE)
async def create_recorded_lesson(request: Request):
    origin = request.headers.get("origin")
    if request.url.hostname not in LOCAL_HOSTS or (origin and urlsplit(origin).hostname not in LOCAL_HOSTS):
        return lesson_form("Open this form from the local Studio address.", 403)
    size = request.headers.get("content-length", "")
    if not size.isdecimal() or int(size) > MAX_WAV_BYTES + 256 * 1024:
        return lesson_form("Choose a WAV recording of 32 MiB or less.", 413)
    async with request.form(max_files=1, max_fields=3) as fields:
        upload = fields.get("wav")
        if not isinstance(upload, UploadFile) or upload.size is None or not 0 < upload.size <= MAX_WAV_BYTES:
            return lesson_form("Choose a nonempty WAV recording of 32 MiB or less.", 422)
        title, locale, transcript = (str(fields.get(name, "")).strip() for name in ("title", "locale", "narration"))
        if not (0 < len(title) <= 160 and 0 < len(locale) <= 32 and 0 < len(transcript) <= 50000):
            return lesson_form("Enter a lesson title, recording language, and transcript.", 422)
        try:
            project = await run_in_threadpool(import_recording, upload, title, locale, transcript)
        except ValidationError as exc:
            return lesson_form(exc.errors()[0]["msg"], 422)
        except ValueError as exc:
            return lesson_form(str(exc), 422)
    return RedirectResponse(f"/studio/{project.project_id}", status_code=303)
