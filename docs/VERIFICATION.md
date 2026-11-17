# Verification record

**Accepted application checks: 20 October 2026. Presentation copy: 20 October 2026.**

The October tests below were run in the earlier accepted release. Arranging that presentation copy did not rerun the application suites; its documentation-only check verified 63 frozen source/test/config/asset files and three approved screenshots. This describes the historical snapshot, not an immutability rule or a current checkout verification. Active development and fresh checks are recorded in dated sections below.

## Historical checks — 20 October 2026

| Scope | Recorded result | What it establishes |
|---|---|---|
| Existing development environment | 484 passed, 10 real-SDK tests skipped, 7 subtests passed in 91.24 seconds; Ruff clean | Behavior covered by the installed-environment suite, using existing optional artifacts. |
| Source-only package core | 208 passed in 2.05 seconds | Seven model-free test files run from the actual package with existing dependencies. |
| Default package AppTest | Passed | Default render with model artifacts absent. |
| Disposable browser journey | Passed | Work controls, fictional-view/Return isolation, fictional unsure answer, parsed JSON/TXT parity, separate text JSON and Clear. |
| Original final archive | Passed in separate Codex QA review | 73 files matched by hash, size and CRC; 63 source bindings, five approved docs/images and five relative links checked. |
| Existing 8505 preview | Camera-off render passed at 07:01:04 UTC | A fresh disposable session rendered without restarting the server. This is dated evidence, not a promise of future uptime. |

The 484-test and 208-test scopes overlap. Do not add them. Skips are not passes. Separate Codex review is a project QA step, not external certification.

## Reproduce the model-free scope

From the project root, with the dependencies available:

```powershell
.\.venv\Scripts\python.exe -B -m pytest -q -rs tests/test_wellbeing.py tests/test_wellbeing_store.py tests/test_personal_patterns.py tests/test_demo_week.py tests/test_session_report.py tests/test_session_measurements.py tests/test_output_summaries.py
```

This covers clock/reminder state, temporary history storage, pattern summaries, fictional data, numeric reports, CSV validation and output summaries. It does not replace browser checks or test physical hardware.

The broader installed-artifact scope is:

```powershell
.\.venv\Scripts\python.exe -B -m ruff check --no-cache app.py stresslens scripts tests
.\.venv\Scripts\python.exe -B -m pytest -q -rs
```

The broader run used local text/Qwen artifacts excluded from this package. It is not a clean-install test. The default policy leaves real face SDK tests skipped without the separate metrics-consent choice.

## Trace the design choices

| Choice | Source | A relevant accepted check |
|---|---|---|
| Explicit clock state | `stresslens/wellbeing.py:21` - `class WorkSession` | `tests/test_wellbeing.py:19` - `test_explicit_work_clock_pauses_resumes_and_ends_without_camera` |
| Answer states stay distinct | `stresslens/personal_patterns.py:6` - `_STRESS = ("none", "low", "high", "unsure", "skipped", "expired")` | `tests/test_wellbeing.py:102` - `test_point_adapter_preserves_existing_self_report_semantics` |
| Fictional example stays isolated | `stresslens/demo_week_ui.py:1` - `Read-only fictional presentation, separate from all personal controllers and I/O.` | `tests/test_demo_week_ui.py:49` - `test_demo_round_trips_preserve_active_clock_report_and_history_preferences` |
| Shared report representations | `stresslens/session_report.py:489` - `def to_export` | `tests/test_session_report.py:324` - `test_json_text_exports_share_schema_and_have_no_inferred_stress` |
| Conflicting readings are rejected | `stresslens/session_report.py:438` - `def add_measurements` | `tests/test_session_report.py:447` - `test_f1_true_source_conflicts_reject_all_pending_changes` |

These pointers describe the fixed source snapshot. They do not assert that a test was repeated during document preparation.

## Version and presentation changes

Frozen source map SHA-256:
`571a5c342ea69876249298c77e9776b5e631a903261c196033a69122d164e913`

Original accepted archive SHA-256:
`85c3327bbdaae9edb0f98b6e23c12f89989c708951f6888b1a4ab7fce0b61783`

These are content identities, not Git commits. The historical record says the original accepted archive was preserved locally; that external archive is not supplied in this repository. The presentation revision changed README and the portfolio story, added setup, this record and a visual PDF, and generated a package manifest while preserving application source and approved screenshots. The original 73-file archive count did not describe the expanded presentation copy and does not describe later development.

`PACKAGE_MANIFEST.json` is now explicitly labelled as a historical 20 October packaging record. Its file hashes, sizes and test results describe that earlier snapshot, not the current checkout. The November documentation already differed from that inventory before the recovery patch. Historical references to a surrounding portfolio folder concern materials outside this repository.

## Fresh checks — 17 November 2026 recovery patch

**Baseline:** Git commit `d7f1eaee02f3d7f9f8634e9bf9a6ecea9ff5678e`. The final checks below cover that baseline plus the recovery patch's summary/test changes. This patch restores project direction and contributor instructions, corrects summary state/scope wording and distinguishes historical packaging evidence from current development. It does not change report schemas, persistence, navigation, camera behavior or models.

| Check | Actual result | Scope |
|---|---|---|
| Unchanged baseline, documented seven-file model-free scope | 208 passed, 1 warning, 1.67 seconds | Fresh baseline run before source/test edits. |
| Summary regression checks before the fix | 4 failed, 8 passed | Expected failures reproduced the missing scope labels and collapsed response states. |
| Summary regression checks after the initial fix | 12 passed, 1 warning, 0.08 seconds | Explicit unsure/skipped/expired counts, real zero ratings, empty data, non-mutation and existing camera descriptions. |
| Final seven-file model-free scope | 210 passed, 1 warning, 1.65 seconds | Same scope as the baseline with two added test cases; no failures or skips. |
| Ruff 0.17.0 | All checks passed | `app.py`, `stresslens`, `scripts` and `tests`. |
| Dependency index listing | All 87 exact lock pins listed for the current target | Availability only; no dependency resolution or full application installation. |

The final run also includes the reviewed wording correction from clarity "supplied" to "rated": an unsure response is supplied, but it is not a specific clarity rating. Its two focused assertions failed before that correction and passed in the final scope.

These are overlapping scopes and before/after runs; do not add their counts. The 210-test scope does not replace the historical 484-test installed-artifact scope.

**Environment:** Linux x86_64, Python 3.12.14, pytest 9.2.0, Ruff 0.17.0. A separate verification virtual environment inherited system site packages. Only pytest, its missing small dependencies and Ruff were installed for this work; no application lock, face SDK, model weights or research datasets were installed. The single pytest warning came from the inherited AnyIO 4.14.2 plugin importing pytest's deprecated `CallSpec2` alias (`PytestRemovedIn10Warning`); it was not suppressed.

The commands below ran from the project root using the verification environment's Python. The model-free run also set pytest's `cache_dir` to a scratch directory outside the checkout; this does not change the test scope.

```text
python -B -m pytest -q -rs tests/test_output_summaries.py
python -B -m pytest -q -rs tests/test_wellbeing.py tests/test_wellbeing_store.py tests/test_personal_patterns.py tests/test_demo_week.py tests/test_session_report.py tests/test_session_measurements.py tests/test_output_summaries.py
python -B -m ruff check --no-cache app.py stresslens scripts tests
```

The two checked Python files have these SHA-256 content identities:

| File | SHA-256 |
|---|---|
| `stresslens/output_summaries.py` | `d671f19cfee434315f6ca6a7bbcf5071cd66b641d07ba276b534493072f0f88d` |
| `tests/test_output_summaries.py` | `adb95c603014c0414b1b308bcf6948a64200441fb173b7799911bd7af609ef0f` |

An independent AI-assisted review inspected the code, new instructions, source hashes and historical manifest preservation. It found no critical or important issues; two wording clarifications were applied and covered by the final checks. This is project QA, not external certification.

**Not rerun or established here:** the full installed-artifact suite, Streamlit AppTests, a browser journey, the owner's Windows/Python 3.13 environment, physical camera/SDK performance, a clean application installation, user benefit or scientific prediction validity. Existing screenshots and the PDF remain dated presentation examples.

## Remaining limits

Physical-camera/SDK performance, phone/watch operation, scientific stress validation and clean-machine setup remain unverified. The optional camera-rate decline has no established cause. No clinical accuracy, guaranteed 10 Hz, production deployment, user adoption or business impact is claimed.

Screenshots are approved captures from disposable fictional QA state, taken on 20 October 2026. They do not contain participant data. The repository is public; a project-code license has not been selected.


## Fresh checks — 17 November 2026 milestone 2

Baseline: `d6ff1cf5c34396a7d982f0d9c43bd7504c9e6610`, recovery branch. Implemented a derived current/latest-ended work report, explicit closing-answer association, categorical counts and separate work-report/1 JSON/TXT exports. Older/restored history is excluded; original ledger exports remain unchanged.

Environment: owner's existing Windows Python 3.13.15, Streamlit 1.65.0, existing project virtual environment; no dependencies installed or security settings changed. Work performed in an isolated local checkout, not the running app source. All test records fictional; history paths temporary.

Initial normal-plugin pytest invocation made no output/progress visible and was stopped after identifying only this task's two test process IDs. Partial output appeared on termination; no pass is claimed for that run. Cause unestablished. With `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`, the first bounded diagnostic run passed 230 tests in 17.79 seconds. Review then added a regression preventing a closing checkbox choice from carrying into another work session.

Final command (using the existing environment's Python, with plugin autoload disabled):

```text
python -B -m pytest -q -rs tests/test_wellbeing_ui.py tests/test_demo_week_ui.py tests/test_wellbeing.py tests/test_wellbeing_store.py tests/test_personal_patterns.py tests/test_demo_week.py tests/test_session_report.py tests/test_session_measurements.py tests/test_output_summaries.py
python -B -m ruff check --no-cache app.py stresslens scripts tests
```

Actual final results: **231 passed in 32.38 seconds; Ruff all checks passed**. This is one overlapping nine-file scope, not additive to historical counts. Fictional Streamlit AppTests cover Start/answer/Pause/Resume/End, standalone versus explicitly attached closing answers, stopped elapsed time, empty/second sessions, restored history exclusion, Clear, unsure/skipped/zero answers, export serialization parity and download controls. Existing demo isolation tests passed. The run used no SDK consent option or model downloads; no physical camera was started.

Limitations: AppTest is not a real-browser visual/download interaction. Serialized JSON/TXT payload parity was checked, not browser-downloaded bytes. Full installed-artifact suite, real hardware, clean install, scientific validity and current running app were not tested. A real-browser disposable visual/download journey remains the next milestone-2 acceptance gate. The live laptop app has not been switched to this checkout. No claim of completed milestone 2 or completed Stage 2.


## Browser check — 17 November 2026

Tested recovery commit 3db968b in a separate localhost port 8507 preview on the existing Windows environment, in a disposable in-app browser tab, with history and camera off. Start → fictional Low/Mixed check-in → Pause → Resume → End rendered the work-session report and a categorical chart showing one Low and one Mixed. Browser downloads were opened locally and compared: JSON and the TXT embedded payload matched; both recorded one fictional check-in and 9.8498666 active seconds. No personal history was accessed; the disposable preview was stopped afterwards. The in-app browser view was narrow, and chart category labels were vertical; broader responsive review remains useful. Prior AppTests, not this browser journey, cover closing check-in, restored history, Clear and the second session.

Independent review noted that downloads taken while work is running can legitimately differ in active time. The report now labels each running download as a snapshot; the on-screen details round active seconds to one decimal while exports preserve the measured value. This is descriptive test evidence, not hardware or scientific validation.


## Fresh environment check — 17 November 2026

A separate Windows Python 3.13.15 virtual environment on the same laptop installed the pinned requirements-lock.txt successfully. The commands were `py -3.13 -m venv <isolated-path>`, then `<isolated-path>\Scripts\python.exe -B -m pip install --disable-pip-version-check -r requirements-lock.txt` from this checkout. `python -B -m pip check` reported no broken requirements; imports reported Streamlit 1.65.0, pandas 2.3.3 and NumPy 2.5.4. The installation log is retained locally outside the repository. A preliminary wheel-only resolution failed for langdetect, which was then successfully built from its source distribution by the documented standard installation. The documented installation is not wheel-only.

With pytest plugin autoload disabled, the fresh environment ran `python -B -m pytest -q -rs tests/test_wellbeing_ui.py tests/test_demo_week_ui.py`: 21 passed in 12.13 seconds, using disposable fictional AppTest inputs. Independently, a localhost-only browser on port 8508 rendered Work session and completed Start → fictional Unsure check-in → End, displaying 0/1 rated and one unsure; camera/history remained off. The test preview was stopped. This is a fresh environment on an existing laptop, not a clean-machine or other-operating-system validation. No model weights or raw participant datasets were downloaded, and no SDK/camera consent was enabled. Windows security remained enabled. The retained isolated audit directory measured 1.46 GiB. Overall free disk fell by roughly 16 GB during the installation, but cache, temporary files and concurrent activity were not separately attributed.

After the report presentation clarification, in the original project environment with pytest plugin autoload disabled, `python -B -m pytest -q -rs tests/test_wellbeing_ui.py` returned 18 passed in 16.35 seconds, and `python -B -m ruff check --no-cache app.py stresslens scripts tests` passed. The scope overlaps previous tests; counts must not be added.
