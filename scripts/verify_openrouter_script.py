"""Run one explicitly authorized free, script-only acceptance test from the repository root."""

import argparse
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
from uuid import uuid4


ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
REQUEST_LIMIT = 12
WALL_SECONDS = 260


def worker(directory: Path, transport=None) -> int:
    import httpx
    from langsmith import tracing_context
    from app.core.config import settings
    from app.core.language import verify_output_language
    from app.models.schemas import ScriptDraft, TrainingVideoRequest
    from app.services.llm.openrouter_provider import OpenRouterProvider
    from app.workflows.manifest import ProjectManifestManager
    from app.workflows.script_generation import create_script_workflow
    from app.workflows.script_generation.validators import validate_script_draft

    logging.disable(logging.CRITICAL)
    settings.OPENROUTER_FALLBACK_MODELS = ""
    stage = "initialization"
    requests = 0
    started = time.monotonic()
    journal = directory / "requests.jsonl"

    def event(kind, **fields):
        record = dict(event=kind, elapsed_s=round(time.monotonic() - started, 3),
                      request=requests, stage=stage, **fields)
        with journal.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def before(request):
        nonlocal requests
        if str(request.url) != ENDPOINT or json.loads(request.content)["model"] != "openrouter/free":
            raise ValueError("Unapproved model or endpoint.")
        if requests >= REQUEST_LIMIT:
            raise ValueError("Acceptance request ceiling reached.")
        requests += 1
        event("dispatch")

    def after(response):
        response.read()
        try:
            body = response.json()
        except ValueError:
            body = {}
        body = body if isinstance(body, dict) else {}
        choices = body.get("choices") or [{}]
        choice = choices[0] if isinstance(choices[0], dict) else {}
        usage = body.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        def label(value):
            return value if isinstance(value, str) and re.fullmatch(r"[\w/:.\-]{1,150}", value) else None
        tokens = {k: v for k, v in usage.items() if k in ("prompt_tokens", "completion_tokens", "total_tokens")
                  and isinstance(v, int)}
        if isinstance(details.get("reasoning_tokens"), int):
            tokens["reasoning_tokens"] = details["reasoning_tokens"]
        event("response", http=response.status_code, model=label(body.get("model")),
              finish_reason=label(choice.get("finish_reason") or choice.get("native_finish_reason")), tokens=tokens)

    class ObservedProvider(OpenRouterProvider):
        def generate_structured(self, prompt, schema, **kwargs):
            nonlocal stage
            stage = schema.__name__
            try:
                return super().generate_structured(prompt, schema, **kwargs)
            except Exception as exc:
                cause = exc
                while cause.__cause__ is not None:
                    cause = cause.__cause__
                event("error", category=getattr(exc, "classification", type(exc).__name__),
                      code=getattr(exc, "status_code", None), cause=type(cause).__name__,
                      errno=getattr(cause, "errno", None))
                raise

    manager = ProjectManifestManager(storage_base_dir=directory)
    pid = directory.name
    request = TrainingVideoRequest(
        topic="How to Make Egyptian Macaroni Béchamel in 60 Seconds",
        source_content=(
            "Teach these six steps, one per scene. 1. Introduce the pasta bake and preheat the oven to 200 C. "
            "2. Boil penne in salted water until just underdone and drain. 3. Soften chopped onion, "
            "add ground beef, season, and brown thoroughly. 4. Cook flour in butter briefly, then gradually "
            "whisk in milk until the béchamel is smooth and thick. 5. Coat pasta with some sauce, layer half "
            "the pasta, the beef, and the remaining pasta in a baking dish. Cover with the remaining sauce. "
            "6. Bake until bubbling and golden, then rest before slicing. Sixty seconds is the video length."
        ),
        source_language="en-US", base_language="ar-SA", target_languages=["ar-SA"],
        audience="Home cooks", target_duration_seconds=60,
    )
    manifest = manager.create_manifest(pid, request)
    manifest.script_status = "running"
    manager.save_manifest(manifest)
    with httpx.Client(trust_env=False, follow_redirects=False, transport=transport,
                      event_hooks={"request": [before], "response": [after]}) as client, tracing_context(enabled=False):
        provider = ObservedProvider(model="openrouter/free", base_url=ENDPOINT.rsplit("/", 2)[0], client=client)
        state = create_script_workflow(provider).invoke({"request": request})
    if state.get("workflow_status") == "completed" and state.get("final_script"):
        draft = ScriptDraft.model_validate(state["draft_script"].model_dump())
        valid = validate_script_draft(draft, 60, analysis=state["analysis"], language="ar-SA").is_valid
        if (valid and draft.language == "ar-SA" and len(draft.scenes) == 6
                and all(s.narration.strip() and verify_output_language(s.narration, "ar-SA")[0] for s in draft.scenes)):
            (directory / "script-draft.json").write_text(draft.model_dump_json(indent=2), encoding="utf-8")
            manifest.script_status = "completed"
            manifest.final_script = state["final_script"]
            manager.save_manifest(manifest)
            event("validated", scenes=6, estimated_seconds=draft.total_estimated_duration_seconds)
            return 0
    manifest.status = manifest.script_status = "failed"
    manifest.record_error(stage="script", code="ACCEPTANCE_FAILED", message=f"Script acceptance failed at {stage}. See request journal.")
    manager.save_manifest(manifest)
    event("failed", workflow_status=state.get("workflow_status"))
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live requires explicit authorization for one run")
    if args.worker:
        try:
            return worker(args.worker)
        except Exception as exc:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            diagnostic = {"category": type(exc).__name__, "file": Path(frame.filename).name, "line": frame.lineno}
            (args.worker / "worker-error.json").write_text(json.dumps(diagnostic), encoding="utf-8")
            return 1
    directory = Path("tmp") / ("script_acceptance_" + uuid4().hex[:12])
    directory.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    env = dict(os.environ, LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false",
               STORAGE_PATH=str(directory.resolve()), LOG_LEVEL="CRITICAL")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.verify_openrouter_script", "--live", "--worker", str(directory)],
            env=env, timeout=WALL_SECONDS - (time.monotonic() - started), capture_output=True,
        )
        status = "passed" if result.returncode == 0 else "failed"
        if result.returncode and not (directory / "requests.jsonl").exists():
            status = "failed_before_dispatch"
    except subprocess.TimeoutExpired:
        status = "deadline"
    summary = {"status": status, "total_seconds": round(time.monotonic() - started, 2), "directory": str(directory.resolve())}
    (directory / "result.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    return int(status != "passed")


if __name__ == "__main__":
    sys.exit(main())
