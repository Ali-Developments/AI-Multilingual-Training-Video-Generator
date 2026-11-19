# Script checkpoint and resume repair

The previous acceptance run recorded five completed SceneDraft responses. Its journal omitted scene IDs, repair labels, accepted objects and validation events. The exact accepted-scene count cannot be determined. There are no saved analysis, outline or scene objects from which to resume that run.

## Implemented behavior

The canonical-script orchestrator creates an atomic checkpoint in the project's script_checkpoints directory. Its identity includes the source request, configured model and checkpoint version. It saves accepted analysis, normalized outline and independently validated scenes. Normal retries load those objects and reconstruct previous-scene context in order, then perform assembly and the existing full-script validation and targeted repairs. Each successful replacement is persisted. A scene accepted individually may still require duration or objective-coverage repair at assembly.

Source or model changes select a different checkpoint. Forced regeneration creates a new generation ID retained by later retries. Previous checkpoint files remain available. Checkpoint reads validate objects against Pydantic. Writes flush and sync a temporary file before atomic replacement. A crash between receiving a response and persisting it can repeat that one request.

Events record scene IDs, generation, language repair, JSON repair, targeted repair and validation. HTTP events record routed model, finish reason, usage and classification. They exclude raw responses and private reasoning. Project metadata exposes script_progress with completed, running, failed and pending values.

Each run stores an expiring lease. Project reads after expiry report failed with SCRIPT_INTERRUPTED and project unfinished running steps as failed. This is a read-time recovery view that does not rewrite existing data. Retry persists the new run state. Old running manifests without leases also read as interrupted. A crash is detected by lease expiry, not immediately.

OPENROUTER_TIMEOUT_SECONDS configures the request budget. OPENROUTER_SCRIPT_TIMEOUT_SECONDS configures the run deadline. Response reading checks elapsed time between chunks and reduces the remaining read timeout. Retry sleeps and new dispatches respect the run deadline. Enforcement during blocked I/O depends on the transport. Retain a process watchdog when testing a strict wall-clock ceiling.

## Model and concurrency decisions

Only the configured primary model is attempted. Automatic model alternatives are disabled. A fixed free model ID can make model selection predictable, but requires an approved availability check and an Arabic structured-output test before use. The free router remains variable. Public documentation confirms random selection with feature filtering and exposes model capabilities through supported parameters. This task read documentation without calling the model catalog or generation API. [Free-router documentation](https://github.com/OpenRouterTeam/docs/blob/main/guides/routing/routers/free-router.mdx) and [model discovery](https://openrouter.ai/docs/api/api-reference/models/get-models).

Scene generation stays sequential because each prompt uses the preceding narration. Parallel calls would alter continuity and increase rate-limit exposure. Project execution locks remain in-process. Multiple backend workers require shared execution locking. The persisted per-project request ceiling continues across resumes.

## Files changed in this task

- app/workflows/script_generation/checkpoint.py
- app/workflows/script_generation/staged_generator.py
- app/workflows/script_generation/nodes.py
- app/workflows/script_generation/graph.py
- app/workflows/orchestrator.py
- app/workflows/manifest.py
- app/services/llm/openrouter_provider.py
- app/core/config.py
- tests/test_openrouter_provider.py
- tests/test_script_checkpoints.py
- docs/SCRIPT_CHECKPOINT_RESUME.md

The checkout already contained prior changes. This list identifies this task's edits.

## Offline verification

The production graph regression interrupts six-scene Arabic generation after two accepted scenes, reconstructs the graph and checkpoint, and completes using four further requests. Analysis, outline and the two accepted scenes are reused. Tests also cover source/model invalidation, generation IDs, expired and active leases, unchanged manifest bytes during recovery reads, deadlines and response keepalives.

## Proposed live test requiring separate approval

Create a new isolated project using the canonical-script orchestrator and openrouter/free. Permit at most 12 total HTTP dispatches across both portions of the test. Interrupt after two scene-validation events, start a fresh process, and resume that same new project. Request a 260-second watchdog for each portion. Check accepted-content hashes and the resumed scene ID, then validate the final six-scene Arabic draft with Pydantic and business rules. Stop on unexpected failure. Historical acceptance directories remain evidence only.

No live generation was launched for this task.
