# Verification record

**Accepted application checks: 20 October 2026. Presentation copy: 20 October 2026.**

The tests below were run in the earlier accepted release. Arranging this presentation copy did not rerun the application suites. Instead, the documentation-only check verifies that all 63 frozen source/test/config/asset files and all three approved screenshots remain byte-for-byte unchanged.

## Recorded checks

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

These are content identities, not Git commits. The original accepted archive is preserved locally. This presentation copy revises README and the portfolio story; adds setup, this record and a visual PDF; and regenerates its package manifest. Source, tests, configuration, assets and approved screenshots remain unchanged. The original 73-file archive count does not describe this expanded presentation copy.

`PACKAGE_MANIFEST.json` lists the files in this copy, excluding itself. The surrounding portfolio folder's release notes record the new inventory and presentation checks.

## Remaining limits

Physical-camera/SDK performance, phone/watch operation, scientific stress validation and clean-machine setup remain unverified. The optional camera-rate decline has no established cause. No clinical accuracy, guaranteed 10 Hz, production deployment, user adoption or business impact is claimed.

Screenshots are approved captures from disposable fictional QA state, taken on 20 October 2026. They do not contain participant data. Publication and project licensing remain separate steps.
