# Checkpoint/resume reliability audit

Reviewed November 19, 2026, on branch codex/local-e2e-test. This audit inspected the existing dirty worktree and added offline probes. Production code was not changed during this review.

## Readiness decision

**Hold the proposed live resume acceptance test.** Happy-path reuse works, but the implementation does not meet the requested cross-process exclusion, generation-identity invalidation, exactly-once request accounting, or paid-provider approval guarantees. Correct the confirmed defects and repeat offline restart tests before requesting a live run.

## Workflow traced

Project creation checks for an existing manifest and then writes a new one. Those operations are separate. A caller-specified duplicate ID can race. The canonical-script endpoint runs the orchestrator in a thread pool. A process-local class lock serializes its same-project calls. A completed final_script is returned immediately, before checking its generation identity.

Otherwise, the orchestrator opens the checkpoint, records its relative path and a lease expiry, and saves running status. An OpenRouter session installs a pre-request counter callback and a monotonic run deadline. The graph normalizes inputs, reuses or generates analysis, then reuses or generates an outline and sequential scenes. A scene is checkpointed after Pydantic alignment and narration-language/content checks. Assembly performs broader duration and objective validation and can regenerate scenes through targeted repair. The graph finalizes a successful script. The orchestrator finishes the checkpoint, writes scripts/source.json, and saves the final manifest in separate operations.

Retry recreates the graph. Accepted objects are loaded from the checkpoint. Graph revision_count, validation state and repair plans are not restored. Project reads project expired leases into failed state without writing the manifest. The deadline and lease restart on each invocation; the request counter normally persists.

## Confirmed findings

| Priority | Finding | Evidence and consequence |
|---|---|---|
| High | Cross-process execution and budget exclusion are absent | orchestrator.py lines 39–40 and 90–93 use threading.Lock. The two-process probe enters the same project from both processes. With a ceiling of one, both pre-dispatch hooks succeed and the saved counter ends at one. The second process can enter while the first has an active lease. |
| High | Stale writes can reset the budget | The callback reads an in-memory manifest captured at invocation and saves the whole object. A previously loaded manifest saved by another operation can erase the new count. The audit reproduces a count of 12 reverting to zero. Atomic replacement does not prevent lost updates. |
| High | Corrupt checkpoint metadata can erase accounting in the recovery view | A referenced checkpoint containing valid JSON of the wrong shape, such as [], raises outside the narrow JSON-reading catch in manifest.py. Its broad legacy fallback constructs a new ProjectManifest without the original metadata. The reproduced recovered object has no request count. A later save can persist that loss. |
| High | Generation identity is incomplete | checkpoint.py line 15 includes only request fields, model string and VERSION. Prompt text, provider/base URL, reasoning settings, output-token budget, schema/validator revisions, speech-rate assumptions and other critical settings are excluded. Changing prompts and reasoning settings reused the same accepted scene in the probe. |
| High | Completed-script fast path bypasses invalidation | orchestrator.py line 100 returns a completed script before constructing any checkpoint identity. Changing the active model or generation settings can still return the old final script unless regeneration is explicitly forced. |
| High | Paid-primary selection has no runtime approval gate | The provider accepts arbitrary primary IDs. The audit's mocked paid primary reaches transport successfully. Automatic fallback is disabled, but that does not enforce authorization for the configured primary. The factory can also explicitly select Groq. Rendering budget gates do not protect this script dispatch path. |
| High | The total deadline is cooperative during transport I/O | Deadline checks execute before dispatch and after/chunkwise during response reading. They cannot interrupt an already blocked call. The installed HTTP/1.1 transport snapshots read timeout once before its body loop. Updating request.extensions between chunks does not change that local timeout. |
| Medium | Missing checkpoints silently discard resumable work | A missing hashed checkpoint initializes an empty checkpoint. There is no distinction between a new run and missing referenced recovery data. This can regenerate previously accepted work. The counter is retained only if its manifest metadata is intact. |
| Medium | Checkpoint validity is narrower than consistency | get validates one accepted object against its Pydantic schema. It does not bind the dictionary key to scene_id/order, validate event/progress agreement, or prove lineage to the current outline and preceding narration. A scene stored under scene_1 with scene_id scene_99 and failed progress was returned by the probe. |
| Medium | Repair/restart state is incomplete | A previously accepted scene remains cached while its replacement is in flight. If repair fails or the process exits, the old value remains available. Full-script validation may request repair again. Revision limits restart with the graph. A repaired predecessor can also leave later cached scenes referring to its old narration. |
| Medium | Failed checkpoint writes can obscure the original error | put changes memory before saving. Checkpoint construction is outside the orchestrator try block. finish can itself throw during exception handling or after graph completion. A disk error can mask the originating failure and leave only lease expiry to signal interruption. |
| Medium | Progress terminology overstates final acceptance | completed means the individual scene checks passed. Later full-script validation can mark that scene for replacement. Events have timestamps and attempt labels but lack durable run, request and attempt IDs and output hashes. ContentAnalysis language correction has no separate repair label. |

## Atomicity and corruption safety

Checkpoint save writes to a unique sibling temporary file, flushes and fsyncs it, and calls os.replace. A real child-process exit immediately before replacement preserved the old complete accepted scene. Exit immediately after replacement preserved the new complete scene and validation event. This verifies process-crash atomic visibility for those boundaries on this filesystem.

It does not establish power-loss durability of replacement metadata, backup recovery, or concurrent-writer isolation. The parent directory is not synced. Temporary files can remain after interruption. There is no checksum, schema for the complete checkpoint envelope, previous-good generation selection, or compare-and-swap. Malformed JSON raises at construction. Structurally valid but inconsistent JSON can pass partial checks. Concurrent checkpoint writers each replace the entire document from their own snapshot, losing another writer's accepted objects or events.

Manifest writes use atomic replacement but do not fsync their temporary file. scripts/source.json uses a direct write. Checkpoint completion, final script and manifest are not one transaction. A crash between those writes has a different recovery state from a crash at a scene checkpoint.

## Request accounting

On the normal canonical-script route, each OpenRouter _post_chat_completion calls count_request once before transport. The callback checks the persisted count loaded for the run, increments it, and saves the manifest. Retry and JSON-repair probes consumed three counts for three mocked HTTP attempts. Reconstructing the orchestrator with the limit exhausted prevented an additional transport call. Forced regeneration changes the checkpoint generation ID without intentionally clearing this counter.

The counter represents reservations, not exactly confirmed outbound requests. A simulated exit after its save and before client.post persisted one count with zero transport calls. Connection failures also consume a count. This conservative charging is reasonable for a ceiling, but contradicts exactly-once dispatched-request reporting. A local file update and an external network send cannot be made atomic solely by rearranging their order. Ambiguous requests need an explicit reserved/attempted/response-recorded state and durable request IDs.

The ceiling is not safe against concurrent processes, stale whole-manifest saves or legacy-recovery metadata loss. It is also bypassed by direct provider/graph use without script_session, including the existing acceptance harness, which has its own process-local 12-request counter. The harness cannot be reused for a two-process cumulative ceiling without modification. Groq sessions do not use the OpenRouter accounting hook. A settings change can intentionally raise the limit, so the run should record the approved ceiling explicitly.

## Cross-process safety

| Deployment | Assessment |
|---|---|
| One sequential process through canonical-script entry point | Happy-path checkpoint reuse and conservative accounting work. Identity, corruption, finalization and authorization gaps remain. |
| Multiple threads in one process | Same-project canonical-script calls serialize. Duplicate requests after failure execute another attempt sequentially. Other manifest-writing routes are not covered by the execution lock. |
| Multiple independent processes sharing storage | Unsafe. Confirmed duplicate entry, lost increments and possible checkpoint last-writer-wins updates. |
| Multiple application instances | Same problem when storage is shared. Separate storage has separate budgets and no global project execution ownership. |

A lease timestamp is a display/recovery hint. It has no owner token, atomic acquisition, renewal or fencing. Expiry neither cancels the old worker nor excludes a new one. Clock changes can affect wall-clock expiry. A blocked worker can continue after the UI reports failure.

## Timeout details

OPENROUTER_TIMEOUT_SECONDS and OPENROUTER_SCRIPT_TIMEOUT_SECONDS are configurable and positive. The existing tests establish refusal of dispatch after an expired monotonic deadline and refusal of retries whose delay exceeds remaining time. The added blocked-stream probe takes at least 0.09 seconds despite a 0.01-second budget before raising, demonstrating cooperative enforcement.

Installed .venv/Lib/site-packages/httpcore/_sync/http11.py lines 196–203 read the body timeout once and reuse it. Headers, connect, pool and write operations also consume separate timeout phases. HTTP response hooks can read the body before the provider loop, as the existing acceptance harness does. Injected clients use a separate post path. File writes and waiting for the project lock are not covered by the network deadline. A watchdog that terminates the worker remains necessary for a strict wall-clock bound, paired with checkpoint recovery and exclusive ownership.

## Least disruptive recommended fixes

1. Require a per-project OS-backed exclusive lock covering the entire local execution, including budget reservations and checkpoint updates. Key it by canonical storage root and project ID. On Windows a file-region lock can release automatically on process exit. Lease expiry must not bypass an active OS lock. Prove the intended filesystem semantics before supporting shared/network storage. No database migration is needed for the single-laptop deployment.
2. Protect accounting against every writer. Separate an append-only reservation journal from ordinary editable manifest snapshots, or make all manifest updates merge under the same cross-process lock. Persist request IDs, approved ceiling and reservation outcomes. Reject corrupt accounting instead of defaulting it to zero.
3. Fingerprint provider, endpoint, model, prompt/schema/validation versions and critical generation settings. Check this identity before the completed-final-script shortcut. Record outline and preceding-scene dependencies where repair can change continuity.
4. Validate the complete checkpoint envelope and its scene/event/progress invariants. Treat missing referenced checkpoints as explicit recovery failures. Preserve corrupt files and offer an explicit restart policy. Persist graph revision/repair state and distinguish individual acceptance from final validation.
5. Enforce a free-only dispatch policy for this workflow unless explicit paid authorization is represented and checked. Validate endpoint/model configuration before dispatch. Keep automatic fallback disabled and remove obsolete fallback configuration descriptions.
6. Use a cancellable worker/process boundary for the overall deadline and record terminal interruption independently. Replace the ineffective dynamic HTTP/1.1 timeout mutation with a tested transport strategy. Add stable attempt IDs and safe error outcomes to the journal.

These are proposals. This review implements no production fixes or locking migration.

## Test evidence and coverage gaps

Final rerun completed with **159 passed, 1 deselected in 21.34 seconds**, including 13 new audit probes and the existing 146-test selection. The full-video pipeline test remained deselected under this task's restriction. The final log is tmp/ra13.txt. The independent audit-only run is tmp/ra07.txt, with 13 passing probes. An early concurrent-start probe hit its barrier deadline; the final probe starts workers in a controlled order while keeping both executions active, making the lost-update interleaving reproducible.

Sandboxed broad runs stalled in Starlette TestClient startup. A 15-second faulthandler trace located the wait in Windows asyncio _make_self_pipe → socket._fallback_socketpair → accept. The final suite ran outside the sandbox with mocked LLM clients and temporary storage. Interrupted partial runs are not counted as passes. Existing tests were retained.

Final command from the repository root, using the existing Python environment:

    .\.venv\Scripts\python.exe -u -m pytest -q --tb=short -p no:cacheprovider --basetemp=tmp/ra13 tests/test_checkpoint_reliability_audit.py tests/test_script_checkpoints.py tests/test_openrouter_provider.py tests/test_llm_provider.py tests/test_multilingual_source_handling.py tests/test_script_workflow.py tests/test_localization.py tests/test_audit_remediation_phase_a.py -k "not phase_a_smoke_test_30s_pipeline"

| Required scenario | Audit outcome |
|---|---|
| Crash immediately before/after checkpoint persistence | Real child-process exits preserve the complete old/new file respectively. |
| Corrupted checkpoint | Invalid JSON fails explicitly; valid JSON with inconsistent shape or scene identity exposes separate defects. |
| Missing checkpoint | Initializes empty state and permits regeneration. |
| Duplicate resume requests | Threads serialize, but a failed first attempt is followed by a new attempt. Independent processes can overlap. |
| Expired lease | Read-time failed projection works; it does not exclude or stop execution. |
| Two processes | Both enter and pass a one-request reservation ceiling; the stored count is one. |
| Changed source/model | New checkpoint identity, verified by current and existing probes. Completed-final-script shortcut remains a separate bypass. |
| Changed generation configuration/prompts | Does not invalidate the checkpoint, reproduced. |
| Failed scene validation and repair | Existing tests verify structured rejection and bounded language/targeted repairs. Persisted repair-state recovery remains incomplete. |
| Request timeout during response reading | Blocked mocked stream exceeds the deadline before the next chunk check raises. Installed HTTP/1.1 source confirms stale local read timeout. |
| Total deadline reached | Existing test blocks dispatch; blocked I/O cancellation remains unproven. |
| Request ceiling before/after restart | Reconstructed instances retain the ceiling normally. Stale writes, malformed-checkpoint recovery and multiple processes can reset or undercount it. Real process exit after reservation consumes a count before transport. |

The previous stored result reports 146 passing tests and one deselected full-video test. New audit probes cover real process exit before/after replacement, malformed/missing/inconsistent checkpoints, source/model/settings identity behavior, stale-counter rollback, corrupt recovery metadata loss, new-instance ceiling preservation, pre-dispatch reservation interruption, retry/repair charging, paid-primary dispatch, duplicate threads, blocked response reading and two independent processes.

Passing audit probes assert the current observed behavior, including defects. They are evidence, not a green readiness gate. The existing six-scene resume test reconstructs a graph in one interpreter and proves its happy path; it is not a complete process-restart acceptance test. Existing tests cover language repair, invalid structured output and targeted scene repair, but not every crash boundary during a repair.

Still unverified are machine power loss, storage exhaustion, Windows sharing violations under load, shared/network-drive locking, hard cancellation of real DNS/TLS/HTTP operations, and complete graph recovery in a new process with accepted-scene hashes and repair state. No network generation requests were made.

## Artifacts and scope

This audit added tests/test_checkpoint_reliability_audit.py and this report. Temporary test directories and logs are under tmp. Existing project data, checkpoints and previous test artifacts were retained. The branch remains codex/local-e2e-test. No application implementation changes were made during the audit.
