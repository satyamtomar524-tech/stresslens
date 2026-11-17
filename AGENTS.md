# Working on StressLens

## Read before changing the project

1. [Project direction](docs/PROJECT_DIRECTION.md): the owner's goal, current capability and next milestone.
2. [README](README.md), [setup](docs/SETUP.md) and [verification](docs/VERIFICATION.md): current usage and dated evidence.
3. The relevant source and tests; inspect `git status` and the current branch before editing.

Follow the user's current task. Use the next milestone in the project brief only when no narrower priority is given. Work in small, reviewable changes; do not execute the entire roadmap automatically.

## Preserve the goal

StressLens aims to help an individual notice possible stress or mental fatigue earlier during work, choose when to pause, and understand personal patterns. The timer, voluntary check-ins and reports are the foundation. Automatic inference remains an explicit research goal, unfinished and unvalidated. Do not silently redefine the project as only a generic timer or a portfolio display.

Before a change, state the user-visible outcome and which milestone it serves. Distinguish the owner's requirements from implementation assumptions. Record a material scope decision in `docs/PROJECT_DIRECTION.md`; ask a focused question only when the answer would change the product and the existing context does not settle it.

## Code and data contracts

- `app.py` assembles the views. The current Work session view and optional camera view share one report ledger through `ensure_report_controller()` in `stresslens/session_ui.py`.
- `stresslens/wellbeing.py::WorkSession` owns active work time. Paused time, camera-on time and the span between observations are different quantities.
- `stresslens/wellbeing_ui.py::CompanionState` holds clarity and work-session associations in `extras`. `current_records()` adapts point answers; optional restored history can contain other sessions. Do not label all displayed history as the current work session.
- `stresslens/session_report.py::ReportWorkspace` owns the shared observation/report state. Reuse its APIs; do not create a competing ledger or silently change export meaning.
- Short summaries live in `stresslens/output_summaries.py`. Compute them from the displayed source data. Explicitly identify the time range or record scope.
- Preserve none/zero, low, high, unsure, skipped, expired and unavailable states. An unsure answer is an explicit response, not a zero and not an omitted answer.
- Keep self-reports, supplied device readings, camera movement and model outputs distinct. No combined health score, unsupported diagnosis, invented causal statement or claim that a camera coefficient measures stress.
- Camera/SDK use, persistence and model downloads require the existing explicit choices. Starting work must not start the camera. Do not enable SDK telemetry as a side effect of routine testing.
- Fictional examples stay separate from personal state and history. Test with disposable fictional inputs and temporary storage.
- Preserve user records and active sessions. Clearing a report, deleting saved history, ending work and releasing the camera are distinct operations; do not conflate them.

## Verify the change you actually made

Use an isolated environment for dependency work. On the owner's existing Windows setup, consult `docs/SETUP.md` before starting a server; do not replace the active preview or use personal records for checks.

The documented model-free check is:

```text
python -B -m pytest -q -rs tests/test_wellbeing.py tests/test_wellbeing_store.py tests/test_personal_patterns.py tests/test_demo_week.py tests/test_session_report.py tests/test_session_measurements.py tests/test_output_summaries.py
```

Choose additional checks for the actual risk: relevant Streamlit AppTests and a disposable browser journey for UI/state changes, or measured hardware diagnostics for camera behavior. Use the full installed-artifact suite only when the required environment/artifacts are available, and report its scope accurately.

```text
python -B -m ruff check --no-cache app.py stresslens scripts tests
python -B -m pytest -q -rs
```

Do not add `--allow-google-sdk-metrics` without the separate explicit consent. Do not download model weights or raw research datasets merely to make unrelated checks pass. If setup or a check is blocked, record the exact failure and continue with meaningful available checks; do not substitute an old pass count.

For behavior changes, use regression checks that protect the user-visible contract. Avoid tests that only assert a document's wording or mirror an implementation. Do not broaden testing after the concrete risks are sufficiently checked.

## Evidence and handoff

- Append a dated entry to `docs/VERIFICATION.md` for new verification. Include baseline revision, changed scope, environment, exact command, actual result and remaining limits.
- October 2026 test counts are historical and overlapping. A pass, a skip, a missing dependency, a model-artifact requirement and an untested hardware path are different outcomes.
- `PACKAGE_MANIFEST.json` is a historical packaging record, not an inventory of the current checkout. Its frozen-source condition applied to the presentation archive; it does not prohibit future source changes.
- Update README/setup when behavior or usage changes. Describe screenshots and the PDF as dated examples when they have not been regenerated.
- Finish with what changed, why, what was checked and what remains. Do not claim detection accuracy, wellbeing benefits, clean installation, camera performance or user adoption without specific evidence.
- Never commit private check-ins, photos/video, raw datasets, model weights, credentials or environments. Retain third-party attribution and the recorded licensing limits.
