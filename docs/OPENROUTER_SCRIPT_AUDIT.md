# OpenRouter script generation audit

## 1. Executive summary

The checkout contained a partially repaired OpenRouter provider. Its initial structured calls already rejected a response containing only a reasoning field. Its JSON repair call used the text-generation retry policy, omitted the structured token allowance, and could publish an excerpt of the failed generation. A separate parser bug labeled ordinary prose as truncated JSON. These defects were reproducible offline. The historical outline response envelope was unavailable.

## 2. Independent audit

The starting revision was `5b4a151` on `codex/local-e2e-test`. The worktree was already dirty. The OpenRouter provider, staged generator, and two relevant test files were present as untracked files. Their presence on disk did not establish which code the historical server loaded.

| Historical claim | Finding |
|---|---|
| English sources can produce Arabic canonical scripts | Verified by request validation, canonical-language prompts and cross-language workflow tests. A multilingual fixture incorrectly treated the **source** language line as the requested output and masked a failed correction. |
| Groq recovers from JSON-mode rejection | Strict schema, JSON object and prompt-only paths exist. The SDK and application could both retry. The application could sleep even after its final attempt. |
| Free OpenRouter routing is active | The inspected environment and direct IPv4 backend health both reported OpenRouter and `openrouter/free`. Previously the code/example default selected a paid model when the model setting was absent. |
| The proxy conflict was permanently resolved | Direct `127.0.0.1:8000/api/v1/health` was healthy. The port-3000 proxy returned no bytes in 15 seconds. Both wildcard and loopback listeners existed on each port. Their coexistence alone does not identify the cause of the proxy timeout. |
| Creation and generation now have separate errors | Verified in the wizard and FastAPI routes. The wizard retained the created ID in component state but forced script regeneration on every subsequent Studio attempt, including storyboard retries. |
| 83 passing tests established reliability | Independent baseline was **82 passed, 1 failed**. The failure explicitly required extracting a scene from private reasoning. Other mocked tests covered real schema failures but missed the repair-time policy gap, the cold-import cycle, and one source/output-language fixture error. |

## 3. Root cause and evidence

The inspected manifest for `proj_8de2e8e1a455` records a script-stage failure at 17:24:22 UTC on November 18, 2026. It identifies `ScriptDraft`, a failed repair, the free router, and `recursive/flint-v1.0:free`. It lacks the original response envelope, finish reason, usage counters, and initial routed model. The other two named project IDs had no manifest in the inspected project store. The quoted outline failure and the earlier Nemotron-to-Flint routing sequence are user-reported history. The available manifest concerns a different schema.

| Question | What the checkout establishes |
|---|---|
| How can planning reach validation? | Previously any nonempty `message.content` was stringified, including prose or a content-part array. Prose ending without a closing brace triggered the truncation diagnostic. The repair and final error could repeat it. |
| Was content empty and reasoning populated? | Unknown for the reported outline. In the inspected implementation, empty content plus reasoning took a typed error path on initial requests and a retryable server-error path during repair. Neither path returned the separate reasoning field as JSON. |
| Was the model out of tokens, and what was its finish reason? | The historical outline evidence establishes neither. Empty final output with `length` establishes that a limit was reached. The usage breakdown is needed to attribute spending to reasoning. A valid complete instance can still be accepted when the finish reason is `length`. |
| Was truncation misclassified, and was bad output reused? | Yes for plain final-channel prose. Formerly the repair prompt included the invalid output twice, and the terminal error included up to 500 characters. A syntax error alone cannot establish a provider stop reason. |
| Can the free router select different models for initial and repair calls? | Both are separate HTTP requests to the router. The application has no upstream pin on that route. Independent response fixtures exercise a model change and retain per-response attribution in the acceptance journal. |
| Can reasoning be disabled, and is the budget sufficient? | The adapter can request a reasoning effort on explicit model IDs. The dynamic router receives no reasoning control. The optional setting is not proof that any named upstream accepts or honors it. The normal free-model budget floor is 8,192 completion tokens; a post-413 compacted call is limited to 2,048. Neither value guarantees enough final-answer tokens. |
| Would a fixed free model be more reliable? | A verified fixed model could reduce routing variance. No offline test establishes its availability, reasoning behavior, or success rate. No new model ID was chosen. |

Application defects and upstream variability are separate findings. The historical oversize/truncation sequence is consistent with the symptoms. Its exact per-call cause cannot be reconstructed from the persisted error string.

## 4. Files changed in this investigation

Paths below are relative to the repository root. They identify this investigation's edits within an already modified checkout.

| File | Change |
|---|---|
| `.env.example`, `app/core/config.py` | Free OpenRouter default and bounded script settings. |
| `app/services/llm/openrouter_provider.py` | Final-channel extraction, structured repair, safe validation/HTTP diagnostics, request budgeting, per-run candidate isolation, free-only automatic fallbacks, capability-constrained routing, bounded backoff and compaction. |
| `app/services/llm/schema_utils.py` | Object extraction, candidate validation, literal punctuation, schema echoes, placeholder and truncation diagnostics. |
| `app/services/llm/groq_provider.py` | Disable nested SDK retries, bound waits, omit raw failed repair output. |
| `app/models/schemas.py`, `app/api/v1/projects.py` | Strip legacy raw-generation suffixes from diagnostics and return the sanitized current script failure from the endpoint. |
| `app/workflows/orchestrator.py` | Serialize same-project script invocations in the local process, persist per-project dispatch count, isolate provider state, require a finalized result, clear failed script status on successful recovery. |
| `app/workflows/script_generation/nodes.py`, `graph.py` in the same directory | Verify corrected analysis language and terminate after a failed revision. |
| `app/workflows/script_generation/staged_generator.py` | Check requested scene count, outline language and repaired narration, bound the count by duration, ensure the opening type and exact target allocation, fix cold initialization. |
| `web/src/app/create/page.tsx` | Reuse a completed script on retry and identify the existing project and saved inputs. |
| `tests/test_openrouter_provider.py`, `tests/test_multilingual_source_handling.py` | Realistic envelope, HTTP, repair, routing, retry, punctuation and cold-process regressions; correct the contradictory historical fixture. |
| `scripts/verify_openrouter_script.py` | Explicit script-only acceptance harness with an isolated project, safe event journal, free-router pin, dispatch ceiling and subprocess watchdog. |
| `docs/OPENROUTER_SCRIPT_AUDIT.md` | This report. |

## 5. Architecture assessment

The Studio creation path posts one project, then calls `generate-script` using its ID. The endpoint invokes the orchestrator and the production LangGraph workflow. Normalization keeps source language and canonical language separate. Content analysis creates objectives and recommends a scene count. On the free router, the graph generates an outline, then one draft per scene, using previous-scene context, the supplied source excerpt and per-locale speech rates. The rates are 115 words per minute for Arabic and 140 for English.

Assembly normalizes IDs, objective coverage, media plans and estimated narration duration. Business validation checks the assembled script. Only a finalized result is published by the canonical-script route. The existing targeted repair path handles individual scenes. The next Studio request plans the storyboard. The acceptance harness stops at script validation.

Six scenes normally need **eight** completions before any correction. A whole-script retry on storyboard failure would duplicate this cost. Completed scripts are reusable. Intermediate analysis and individual scenes are held in memory; retrying a failed script can redo that work. Persistent partial-stage checkpoints would require source/version matching and invalidation. They were deferred for this local repair.

## 6. Model strategy

Free structured generation requests `json_object` with `provider.require_parameters=true` on initial and repair calls. An unavailable or incompatible endpoint produces a typed failure. The automatic candidate list is limited to the primary and up to two explicitly configured free alternatives. The acceptance harness pins the primary to `openrouter/free` and empties the alternative list.

For production pinning, establish free availability and parameter support, then verify one representative Arabic outline and scene under the actual budget before configuring the candidate. The audit did not query a catalog or benchmark alternative models.

## 7. Offline tests

From the repository root in PowerShell, the final checks used the following commands. Pytest's temporary directory was unique to each run.

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=line -p no:cacheprovider --basetemp=tmp/llm-repair-r5 tests/test_openrouter_provider.py tests/test_llm_provider.py tests/test_multilingual_source_handling.py tests/test_script_workflow.py tests/test_localization.py tests/test_audit_remediation_phase_a.py -k "not phase_a_smoke_test_30s_pipeline"
node --test web/tests/*.test.mjs
node web/node_modules/typescript/bin/tsc --project web/tsconfig.json --noEmit --incremental false
```

**141 Python tests passed, 1 full-pipeline test deselected. All 33 frontend tests passed. TypeScript exited 0.** Before the first live attempt, the then-selected Python suite passed 112 tests with one deselected. The expanded suite includes a cold Python process running the acceptance worker against an in-memory HTTP transport.

Coverage includes valid final content, separated and tagged reasoning, missing content, length stops, reasoning token metadata, malformed and truncated outlines/scenes, schema echoes and placeholder ellipses, missing fields, repair success and failure, strict-format fallback, free routing rejection, 404, 413, 429 and backoff, routed model changes, six-scene Arabic assembly, targeted regeneration, same-project endpoint retries, Groq and multilingual behavior. The six-scene fixture completes in eight mocked requests. Frontend unit tests include simulated request flows; they do not establish successful navigation through the running Studio.

## 8. Remaining risks

Dynamic free capacity, model selection and latency vary between requests. Requesting format support cannot guarantee valid Pydantic fields, coherent instructions, accurate Arabic, or sufficient completion budget. Language detection and duration estimation are heuristics. Structural objective coverage does not prove that narration teaches each objective. Long source material is excerpted for scene prompts.

The local backend defaults to 48 counted OpenRouter script dispatches per project, including normal retries. Its 260-second workflow deadline limits subsequent dispatch and HTTP timeout budgets. HTTPX timeouts are per I/O phase. The acceptance process separately has a hard watchdog. Project locks are in-process; multi-worker deployments would require coordinated locking. Studio retains its project ID in component state, so a page reload loses that retry context. The current Studio proxy health timeout remains unresolved.

## 9. Live verification procedure

After explicit approval, run `.\.venv\Scripts\python.exe -m scripts.verify_openrouter_script --live` from the repository root. Each invocation gets a new UUID directory under `tmp`. The worker sends six English cooking steps, requests Arabic `ar-SA` and a 60-second instructional video script, and runs the production graph. It checks the final draft against Pydantic, business rules, scene count, and narration language before saving it. Only the script graph runs. The 12-dispatch ceiling includes transport retries, and the watchdog covers child startup. The journal records response metadata without prompts, bodies, authorization headers, or reasoning text.

## 10. Acceptance status

The first authorized attempt ended in **0.74 seconds with zero HTTP requests**. It stopped before project creation. A cold import of `app.core.language` initialized the localization package, its validators, the workflow package, and the staged generator, which tried to import `verify_output_language` from the still-initializing module. Pytest's previous import order hid the error. The staged generator now resolves the function at use time. A fresh-process regression exercises that import order through the actual acceptance worker.

The separately authorized attempt in `tmp/script_acceptance_005e85ba22cb` **failed at the 260-second deadline during SceneDraft generation**. The parent recorded **260.02 seconds** including termination overhead. It dispatched **8 of 12 permitted OpenRouter requests**. Seven responses arrived. Each returned HTTP 200 and `finish_reason=stop`. The graph accepted the analysis and outline, then entered scene generation. No assembled Arabic ScriptDraft reached final Pydantic or business validation.

| Request | Stage | Confirmed upstream | Response time, seconds | Completion tokens | Reported reasoning tokens |
|---:|---|---|---:|---:|---:|
| 1 | ContentAnalysis | `nvidia/nemotron-3.5-super-vl:free` | 21.48 | 2,895 | 2,177 |
| 2 | ScriptOutline | `inclusionai/ling-3.2-flash:free` | 104.78 | 4,015 | 1,855 |
| 3 | SceneDraft | `recursive/flint-v1.0:free` | 26.19 | 4,023 | 5,128 |
| 4 | SceneDraft | `baidu/ernie-5.5-flash-preview:free` | 4.12 | 1,072 | 766 |
| 5 | SceneDraft | `dots-studio/dots-3-note-preview:free` | 50.88 | 2,716 | 3,243 |
| 6 | SceneDraft | `particle-ai/particle-1:free` | 4.87 | 956 | 645 |
| 7 | SceneDraft | `liquid/lfm-3-1.7b:free` | 28.96 | 2,623 | 2,383 |
| 8 | SceneDraft | Unreported before deadline | — | — | — |

The runner measured client-observed request time, including upstream waiting. Requests 3 and 5 reported more reasoning tokens than completion tokens. The table preserves those upstream figures; subtracting them would produce a misleading estimate of visible output. The journal identifies schema per request, without recording scene ID or differentiating a fresh scene from a repair. Five scene responses therefore cannot establish five individually accepted scenes.

The watchdog terminated the worker during request 8. The isolated project manifest retained its last saved state, `script_status=running`, with an empty `final_script`. The parent wrote `result.json` with terminal status `deadline`. The sanitized `requests.jsonl` is the per-call evidence. No final draft file exists. The attempt used only the free router. It stopped before storyboard, TTS, avatars, and rendering. No further live run was made.

**Disposition.** The historical outline blocker was passed in this live sample. End-to-end six-scene Arabic script generation within the approved limit remains unverified. This run establishes cumulative live latency as its stopping condition. The eighth request's upstream outcome and the quality of a complete final script are unknown.
